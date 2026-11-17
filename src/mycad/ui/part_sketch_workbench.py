# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent in-viewport sketch workbench for part documents."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from functools import partial
from math import atan2, cos, degrees, dist, radians, sin
from typing import TYPE_CHECKING, Literal, cast, override

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mycad import app
from mycad.core.exceptions import MycadError
from mycad.core.part_sketch_session import PartSketchEditSession
from mycad.core.polyline_curves import polyline_sampled_points
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    Point2D,
    Point3D,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
    SketchSupportFace,
    SplineEntity,
    WorkPlaneFrame,
    new_sketch_identity,
)
from mycad.core.sketch_constraints import (
    SketchConstraint,
    SketchConstraintSolveResult,
    SketchGeometryReference,
)
from mycad.core.sketch_edit import (
    copy_entities,
    extend_curve_at,
    mirror_entities,
    move_sketch_handle,
    offset_entities,
    trim_curve_at,
)
from mycad.core.spatial_frames import RigidFrame
from mycad.core.spatial_positioning import (
    ProjectedAnchor,
    choose_object_snap,
    intersect_plane,
    locate_uv,
)
from mycad.core.spatial_references import SpatialReference
from mycad.ui.cad_icons import set_button_icon
from mycad.ui.part_sketch_dimensions import draft_dimension_leaders, draft_dimensions
from mycad.ui.sketch_constraint_dialog import SketchConstraintDialog
from mycad.ui.sketch_dynamic_input import SketchDynamicInput
from mycad.ui.sketch_editor import SketchCanvas
from mycad.ui.viewport import DraftRelationAnnotation, SelectionState

if TYPE_CHECKING:
    from mycad.core.persistence import LoadedDocument
    from mycad.core.viewport_protocol import ViewportSketchRegion
    from mycad.ui.viewport import GLViewport


class _DimensionEditor(QDoubleSpinBox):
    escape_pressed = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PartSketchWorkbench(QDialog):
    """Edit one uncommitted sketch on a locked part workplane."""

    _source_changed = Signal()

    def __init__(
        self,
        services: app.AppServices,
        loaded: LoadedDocument,
        viewport: GLViewport,
        *,
        session_identity: int,
        current_session: Callable[[], int] | None = None,
        can_execute: Callable[[], bool] | None = None,
        existing_sketch: Sketch | None = None,
        attached_frame: WorkPlaneFrame | None = None,
        support_face: SketchSupportFace | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("零件草图")
        self._loaded = loaded
        self._services = services
        self._viewport = viewport
        self._session_identity = session_identity
        self._current_session = current_session or (lambda: session_identity)
        self._can_execute = can_execute or (lambda: True)
        self._source_revision = loaded.document.revision
        self._candidate = app.create_replay_candidate(
            services, loaded, session_identity=session_identity
        )
        self._saved_view = viewport.capture_view()
        self._saved_selection_filter: Literal["body", "face", "edge", "vertex"] = (
            viewport.selection_filter()
        )
        self._locked = False
        self._finished = False
        self._closed = False
        self._tool = "select"
        self._points: list[Point2D] = []
        self._last_dynamic_point: Point2D | None = None
        self._last_dynamic_infer = True
        self._dynamic_input_error = False
        self._rubber_band_curve: tuple[tuple[float, float, float], ...] = ()
        self._preview_generation: int | None = None
        self._selection_only_preview = False
        self._support: SpatialReference | None = None
        self._snapped_this_point = False
        self._snap_marker: tuple[Point3D, Point3D | None] | None = None
        self._last_snap_reference: SketchGeometryReference | None = None
        self._start_snap_reference: SketchGeometryReference | None = None
        self._original_sketch = existing_sketch
        self._attached_frame = attached_frame
        self._support_face = support_face
        self.constraint_dialog: SketchConstraintDialog | None = None
        self.dimension_editor: _DimensionEditor | None = None
        self._dimension_kind: (
            Literal["length", "distance", "angle", "radius", "diameter"] | None
        ) = None
        self._dimension_references: list[SketchGeometryReference] = []
        self._constraint_edits: list[
            tuple[Sketch, SketchConstraint, SketchConstraintSolveResult]
        ] = []
        self.selected_entity_id: str | None = None
        self.selected_relation_id: str | None = None
        self.selected_dimension_id: str | None = None
        self.selected_region_ids: tuple[str, ...] | None = None
        self._region_mode = False
        self._region_generation: int | None = None
        self._region_candidates: tuple[ViewportSketchRegion, ...] = ()
        self._trim_preview: tuple[int, tuple[float, float], Sketch] | None = None
        self._mirror_target_id: str | None = None
        self._mirror_axis_start: Point2D | None = None
        self._mirror_generation: int | None = None
        self._hovered_region: tuple[str, ...] | None = None
        self._selection_point: tuple[float, float] | None = None
        self._rendered_curves: list[tuple[str, tuple[tuple[float, float, float], ...]]] = []
        self._drag_reference: SketchGeometryReference | None = None
        self._drag_start: tuple[float, float] | None = None
        self.session = PartSketchEditSession(
            existing_sketch or Sketch(new_sketch_identity(), WorkPlaneFrame.xy(), ())
        )
        self._displayed_sketch = self.session.sketch

        self.plane_combo = QComboBox(self)
        if attached_frame is not None and support_face is not None:
            self.plane_combo.addItem("所选模型平面（查询）", (attached_frame, None))
        for name in ("xy", "xz", "yz"):
            self.plane_combo.addItem(
                f"世界 {name.upper()}", (RigidFrame.identity().principal_plane(name), None)
            )
        for datum in viewport.interaction_datums():
            if datum.reference.kind == "datum_plane":
                self.plane_combo.addItem(datum.name, (datum.frame, datum.reference))
        self.lock_button = QPushButton("锁定平面", self)
        self.normal_view_button = QPushButton("正视平面", self)
        self.select_button = QPushButton("选择", self)
        self.point_button = QPushButton("点", self)
        self.line_button = QPushButton("直线", self)
        self.continuous_button = QPushButton("连续线", self)
        self.rectangle_button = QPushButton("矩形", self)
        self.circle_button = QPushButton("圆", self)
        self.arc_button = QPushButton("圆弧", self)
        self.spline_button = QPushButton("样条", self)
        self.trim_button = QPushButton("修剪", self)
        self.extend_button = QPushButton("延伸", self)
        self.offset_button = QPushButton("偏移", self)
        self.mirror_button = QPushButton("镜像", self)
        self.undo_button = QPushButton("撤销", self)
        self.redo_button = QPushButton("重做", self)
        self.constraint_button = QPushButton("约束/尺寸", self)
        self.dimension_button = QToolButton(self)
        self.dimension_button.setText("画布标注")
        self.dimension_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.dimension_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.dimension_menu = QMenu(self.dimension_button)
        for label, kind in (
            ("长度", "length"),
            ("点距", "distance"),
            ("角度", "angle"),
            ("半径", "radius"),
            ("直径", "diameter"),
        ):
            self.dimension_menu.addAction(label).triggered.connect(
                partial(self.begin_dimension_placement, kind)
            )
        self.dimension_button.setMenu(self.dimension_menu)
        set_button_icon(self.dimension_button, "dimension")
        self.region_button = QPushButton("选择区域", self)
        self.toggle_construction_button = QPushButton("切换构造", self)
        self.preview_button = QPushButton("预览", self)
        self.confirm_button = QPushButton("完成草图", self)
        self.confirm_button.setEnabled(False)
        cancel_button = QPushButton("取消草图", self)
        self.status_label = QLabel("选择并锁定草图平面。", self)
        self.object_snap = QCheckBox("对象捕捉", self)
        self.object_snap.setChecked(True)
        self.auto_relations = QCheckBox("自动关系", self)
        self.auto_relations.setChecked(True)
        self.grid_visible = QCheckBox("显示网格", self)
        self.grid_snap = QCheckBox("网格吸附", self)
        self.project_snap = QCheckBox("离面点投影", self)
        self.construction = QCheckBox("构造几何", self)
        self.grid_spacing = QDoubleSpinBox(self)
        self.grid_spacing.setRange(0.001, 100000.0)
        self.grid_spacing.setValue(1.0)
        self.u_field = QDoubleSpinBox(self)
        self.v_field = QDoubleSpinBox(self)
        for field in (self.u_field, self.v_field):
            field.setRange(-1e9, 1e9)
            field.setDecimals(6)
        self.numeric_point_button = QPushButton("输入 UV 点", self)
        self.options_button = QPushButton("捕捉与选项", self)
        self.options_button.setObjectName("partSketchOptions")
        self.options_button.setCheckable(True)
        self.options_button.setProperty("sketchTool", True)
        self.grid_spacing.setMaximumWidth(76)
        self.u_field.setMaximumWidth(105)
        self.v_field.setMaximumWidth(105)
        self._tool_buttons = {
            "select": self.select_button,
            "point": self.point_button,
            "line": self.line_button,
            "continuous": self.continuous_button,
            "rectangle": self.rectangle_button,
            "circle": self.circle_button,
            "arc": self.arc_button,
            "spline": self.spline_button,
            "trim": self.trim_button,
            "extend": self.extend_button,
            "offset": self.offset_button,
            "mirror": self.mirror_button,
        }
        for tool, icon in (
            ("select", "draw-select"),
            ("point", "draw-point"),
            ("line", "draw-line"),
            ("continuous", "draw-polyline"),
            ("rectangle", "draw-rectangle"),
            ("circle", "draw-circle"),
            ("arc", "draw-arc"),
            ("spline", "draw-spline"),
            ("trim", "draw-trim"),
            ("extend", "draw-extend"),
            ("offset", "edit-offset"),
            ("mirror", "edit-mirror"),
        ):
            button = self._tool_buttons[tool]
            button.setCheckable(True)
            button.setProperty("sketchTool", True)
            button.setEnabled(True)
            set_button_icon(button, icon)
        self.select_button.setChecked(True)
        for button, icon in (
            (self.undo_button, "undo"),
            (self.redo_button, "redo"),
            (self.constraint_button, "dimension"),
            (self.confirm_button, "confirm"),
            (cancel_button, "cancel"),
        ):
            set_button_icon(button, icon)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        groups = QHBoxLayout()
        groups.setSpacing(4)

        def group(name: str, title: str, items: tuple[QWidget, ...], columns: int) -> None:
            frame = QFrame(self)
            frame.setObjectName(name)
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            panel = QVBoxLayout(frame)
            panel.setContentsMargins(4, 2, 4, 2)
            panel.setSpacing(2)
            grid = QGridLayout()
            grid.setSpacing(2)
            for index, item in enumerate(items):
                grid.addWidget(item, index // columns, index % columns)
            panel.addLayout(grid)
            caption = QLabel(title, frame)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            panel.addWidget(caption)
            groups.addWidget(frame)

        group(
            "sketchPlaneGroup",
            "平面与视图",
            (self.plane_combo, self.lock_button, self.normal_view_button),
            1,
        )
        group(
            "sketchDrawGroup",
            "选择与绘制",
            (
                self.select_button,
                self.point_button,
                self.line_button,
                self.continuous_button,
                self.rectangle_button,
                self.circle_button,
                self.arc_button,
                self.spline_button,
                self.trim_button,
                self.extend_button,
                self.offset_button,
                self.mirror_button,
            ),
            3,
        )
        group(
            "sketchRelationsGroup",
            "关系与选项",
            (
                self.constraint_button,
                self.options_button,
                self.undo_button,
                self.redo_button,
                self.dimension_button,
                self.region_button,
            ),
            2,
        )
        group(
            "sketchFinishGroup",
            "草图",
            (
                self.preview_button,
                self.confirm_button,
                cancel_button,
            ),
            1,
        )
        groups.addStretch()
        layout.addLayout(groups)
        self.dynamic_input = SketchDynamicInput(self)
        self.dynamic_input.changed.connect(self._on_dynamic_input_changed)
        self.dynamic_input.escape_requested.connect(self._cancel_dynamic_entity)
        layout.addWidget(self.dynamic_input)
        self.offset_controls = QWidget(self)
        offset_layout = QHBoxLayout(self.offset_controls)
        offset_layout.setContentsMargins(0, 0, 0, 0)
        offset_layout.addWidget(QLabel("偏移距离（正负决定方向）", self.offset_controls))
        self.offset_distance = QDoubleSpinBox(self.offset_controls)
        self.offset_distance.setRange(-1e9, 1e9)
        self.offset_distance.setDecimals(6)
        self.offset_distance.setSuffix(" mm")
        self.offset_distance.setValue(1)
        offset_layout.addWidget(self.offset_distance)
        offset_layout.addStretch()
        self.offset_controls.hide()
        layout.addWidget(self.offset_controls)
        self.mirror_keep_source = QCheckBox("镜像时保留原件", self)
        self.mirror_keep_source.setChecked(True)
        self.mirror_keep_source.hide()
        layout.addWidget(self.mirror_keep_source)
        snap_controls = QHBoxLayout()
        for item in (
            self.object_snap,
            self.auto_relations,
            self.grid_visible,
            self.grid_snap,
            self.project_snap,
            self.construction,
        ):
            snap_controls.addWidget(item)
        snap_controls.addStretch()
        numeric_controls = QHBoxLayout()
        numeric_controls.addWidget(QLabel("网格间距", self))
        numeric_controls.addWidget(self.grid_spacing)
        numeric_controls.addWidget(self.toggle_construction_button)
        numeric_controls.addWidget(QLabel("U", self))
        numeric_controls.addWidget(self.u_field)
        numeric_controls.addWidget(QLabel("V", self))
        numeric_controls.addWidget(self.v_field)
        numeric_controls.addWidget(self.numeric_point_button)
        numeric_controls.addStretch()
        self.options_panel = QWidget(self)
        options_layout = QVBoxLayout(self.options_panel)
        options_layout.setContentsMargins(4, 0, 4, 0)
        options_layout.setSpacing(2)
        options_layout.addLayout(snap_controls)
        options_layout.addLayout(numeric_controls)
        self.options_panel.hide()
        self.options_button.toggled.connect(self.options_panel.setVisible)
        layout.addWidget(self.options_panel)
        layout.addWidget(self.status_label)
        self.lock_button.clicked.connect(self.lock_plane)
        self.normal_view_button.clicked.connect(self._look_at_plane)
        self.grid_visible.toggled.connect(self._update_grid)
        self.grid_spacing.valueChanged.connect(self._update_grid)
        self.numeric_point_button.clicked.connect(
            lambda: self.place_uv((self.u_field.value(), self.v_field.value()))
        )
        self.select_button.clicked.connect(lambda: self.select_tool("select"))
        self.point_button.clicked.connect(lambda: self.select_tool("point"))
        self.line_button.clicked.connect(lambda: self.select_tool("line"))
        self.continuous_button.clicked.connect(lambda: self.select_tool("continuous"))
        self.rectangle_button.clicked.connect(lambda: self.select_tool("rectangle"))
        self.circle_button.clicked.connect(lambda: self.select_tool("circle"))
        self.arc_button.clicked.connect(lambda: self.select_tool("arc"))
        self.spline_button.clicked.connect(lambda: self.select_tool("spline"))
        self.trim_button.clicked.connect(lambda: self.select_tool("trim"))
        self.extend_button.clicked.connect(lambda: self.select_tool("extend"))
        self.offset_button.clicked.connect(lambda: self.select_tool("offset"))
        self.mirror_button.clicked.connect(lambda: self.select_tool("mirror"))
        self.offset_distance.valueChanged.connect(self._offset_distance_changed)
        self.mirror_keep_source.toggled.connect(self._mirror_options_changed)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.constraint_button.clicked.connect(self.open_constraint_dialog)
        self.region_button.clicked.connect(self.begin_region_selection)
        self.toggle_construction_button.clicked.connect(self.toggle_selected_construction)
        self.preview_button.clicked.connect(self.preview)
        self.confirm_button.clicked.connect(self.confirm)
        cancel_button.clicked.connect(self.reject)
        viewport.installEventFilter(self)
        viewport.datum_selection_changed.connect(self._on_datum_selected)
        viewport.selection_changed.connect(self._on_face_selected)
        if existing_sketch is None:
            viewport.set_selection_filter("face")
        self.finished.connect(self._cleanup)
        self._source_changed.connect(self._expire_if_changed)
        for event in (
            "post_command",
            "command_amended",
            "geometry_rebuilt",
            "metadata_changed",
            "named_group_added",
            "named_group_removed",
        ):
            loaded.document.events.subscribe(event, self._on_document_event)
        if existing_sketch is not None:
            self._viewport.set_active_draft_sketch(existing_sketch.sketch_id)
            self._locked = True
            self.plane_combo.insertItem(0, "已有草图平面")
            self.plane_combo.setCurrentIndex(0)
            self.plane_combo.setEnabled(False)
            self.lock_button.setEnabled(False)
            self._viewport.look_at_workplane(existing_sketch.frame)
            self._invalidate_preview()
            fit_points = [point for _, curve in self._rendered_curves for point in curve]
            fit_points.extend(item.position for item in self._viewport.draft_sketch_dimensions())
            self._viewport.fit_world_points(fit_points, margin=1.6)
            self.status_label.setText("编辑已有草图；确认前将预演下游模型。")

    def _look_at_plane(self) -> None:
        if not self._is_current():
            return
        if self._locked:
            self._viewport.look_at_workplane(self.session.sketch.frame)
        else:
            data = cast("object", self.plane_combo.currentData())
            if isinstance(data, tuple) and isinstance(data[0], WorkPlaneFrame):
                self._viewport.look_at_workplane(data[0])

    def _on_face_selected(self, selection: object) -> None:
        if self._locked or not self._is_current() or not isinstance(selection, SelectionState):
            return
        if selection.kind != "face" or len(selection.topology_ids) != 1:
            return
        try:
            descriptor = app.interactive_selectors(self._services, "face", selection.topology_ids)[
                0
            ]
            if descriptor.get("surface") != "plane":
                self.status_label.setText("草图只能附着到平面；请重新选择模型面。")
                return
            face = app.interactive_face_frame(self._services, selection.topology_ids[0])
            frame = WorkPlaneFrame.from_planar_face(face.origin, face.normal)
            self._support_face = SketchSupportFace.from_mapping(descriptor)
        except (MycadError, ValueError) as exc:
            self.status_label.setText(f"无法选择草图平面：{exc}")
            return
        index = self.plane_combo.findText("所选模型平面（查询）")
        if index < 0:
            self.plane_combo.insertItem(0, "所选模型平面（查询）", (frame, None))
            index = 0
        else:
            self.plane_combo.setItemData(index, (frame, None))
        self.plane_combo.setCurrentIndex(index)
        self.status_label.setText("已选择模型平面；锁定后开始绘制。")

    def _on_datum_selected(self, reference: object) -> None:
        if self._locked or not self._is_current() or not isinstance(reference, SpatialReference):
            return
        for index in range(self.plane_combo.count()):
            data = cast("object", self.plane_combo.itemData(index))
            if not isinstance(data, tuple):
                continue
            pair = cast("tuple[object, ...]", data)
            if len(pair) == 2 and pair[1] == reference:
                self.plane_combo.setCurrentIndex(index)
                self.status_label.setText("已选择基准平面；锁定后开始绘制。")
                return

    def _on_document_event(self, _payload: Mapping[str, object]) -> None:
        if not self._finished and not self._closed:
            self._source_changed.emit()

    def _expire_if_changed(self) -> None:
        if (
            self._finished
            or self._closed
            or self._loaded.document.revision == self._source_revision
        ):
            return
        self._preview_generation = None
        self.confirm_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.numeric_point_button.setEnabled(False)
        self._close_dimension_editor()
        if self._current_session() == self._session_identity:
            self._viewport.clear_candidate_preview()
            self._viewport.set_draft_sketch_curves(())
            self._viewport.set_draft_sketch_points(())
            self._viewport.set_draft_sketch_control_points(())
            self._viewport.set_draft_relation_labels(())
            self._viewport.set_draft_sketch_dimensions(())
            self._viewport.set_draft_sketch_regions(())
        self.status_label.setText("模型已改变，草稿保留；请退出后重新开始。")

    def _is_current(self) -> bool:
        return (
            not self._finished
            and not self._closed
            and self._current_session() == self._session_identity
            and self._loaded.document.revision == self._source_revision
        )

    @property
    def has_draft(self) -> bool:
        """Whether a local entity or unfinished point would be lost on exit."""
        if self.dimension_editor is not None:
            return True
        if self._dimension_kind is not None:
            return True
        if self._original_sketch is not None:
            return bool(self.session.sketch != self._original_sketch or self._points)
        return bool(self.session.sketch.entities or self._points)

    @property
    def displayed_sketch(self) -> Sketch:
        """Return the exact draft geometry currently shown in the overlay."""
        return self._displayed_sketch

    @property
    def preview_curve(self) -> tuple[tuple[float, float, float], ...]:
        return self._rubber_band_curve

    @property
    def pending_point_count(self) -> int:
        return len(self._points)

    @property
    def mirror_target_id(self) -> str | None:
        return self._mirror_target_id

    @property
    def mirror_axis_start(self) -> Point2D | None:
        return self._mirror_axis_start

    def lock_plane(self) -> None:
        """Lock a supported plane and orient the original viewport to it."""
        if not self._can_execute():
            self.status_label.setText("请等待当前操作完成后再锁定草图平面。")
            return
        if self._locked or not self._is_current():
            return
        data = cast("object", self.plane_combo.currentData())
        if not isinstance(data, tuple):
            return
        pair = cast("tuple[object, ...]", data)
        if len(pair) != 2:
            return
        frame, support = pair
        if not isinstance(frame, WorkPlaneFrame) or not (
            support is None or isinstance(support, SpatialReference)
        ):
            return
        support_face = (
            self._support_face if self.plane_combo.currentText() == "所选模型平面（查询）" else None
        )
        self.session = PartSketchEditSession(
            Sketch(new_sketch_identity(), frame, (), support_face=support_face)
        )
        self._support = support
        self._locked = True
        for button in self._tool_buttons.values():
            button.setEnabled(True)
        self.plane_combo.setEnabled(False)
        self.lock_button.setEnabled(False)
        self._viewport.look_at_workplane(frame)
        self._viewport.setFocus()
        self._update_grid()
        self.status_label.setText(
            "平面已锁定，选择绘图点。" if self._tool != "select" else "平面已锁定，选择绘图工具。"
        )

    def _update_grid(self) -> None:
        frame = (
            self.session.sketch.frame if self._locked and self.grid_visible.isChecked() else None
        )
        self._viewport.set_workplane_grid(frame, self.grid_spacing.value())

    def _pointer_uv(self, x: float, y: float, *, bypass: bool) -> Point2D | None:
        self._snapped_this_point = False
        self._snap_marker = None
        self._last_snap_reference = None
        plane = self.session.sketch.frame
        ray = self._viewport.camera_ray(x, y)
        point = None if ray is None else intersect_plane(*ray, plane)
        if point is None:
            self._viewport.set_position_markers(None)
            return None
        if self.object_snap.isChecked() and not bypass:
            anchors: list[ProjectedAnchor] = []
            references: dict[str, SketchGeometryReference] = {}

            def add_anchor(
                kind: Literal["origin", "vertex", "center", "midpoint"],
                key: str,
                world: tuple[float, float, float],
            ) -> None:
                screen = self._viewport.project_world_point(world)
                if screen is not None:
                    anchors.append(ProjectedAnchor(kind, key, world, screen))

            add_anchor("origin", "workplane", plane.origin_mm)
            if self._viewport.coordinate_axes_visible():
                add_anchor("origin", "world", (0.0, 0.0, 0.0))
            for anchor in self._viewport.interaction_snap_anchors():
                key = anchor.source_key or str(
                    anchor.topology_id.value if anchor.topology_id else ""
                )
                if key:
                    add_anchor(anchor.kind, key, anchor.point)
            for entity in self.session.sketch.entities:
                if not self.session.sketch.layers.get(entity.layer_name).displayed:
                    continue
                if isinstance(entity, PointEntity):
                    local = (entity.position_mm,)
                elif isinstance(entity, LineEntity):
                    local = (entity.start_mm, entity.end_mm)
                elif isinstance(entity, SplineEntity):
                    local = (entity.control_points_mm[0], entity.control_points_mm[-1])
                elif isinstance(entity, RectangleEntity):
                    u1, v1 = entity.first_corner_mm
                    u2, v2 = entity.opposite_corner_mm
                    local = ((u1, v1), (u2, v1), (u2, v2), (u1, v2))
                elif isinstance(entity, (CircleEntity, ArcEntity)):
                    local = (entity.center_mm,)
                else:
                    continue
                for index, value in enumerate(local):
                    key = f"{entity.entity_id}:{index}"
                    kind = "center" if isinstance(entity, (CircleEntity, ArcEntity)) else "vertex"
                    add_anchor(kind, key, plane.local_to_world(value))
                    if isinstance(entity, LineEntity | SplineEntity):
                        references[key] = SketchGeometryReference(
                            entity.entity_id, "start" if index == 0 else "end"
                        )
                    elif isinstance(entity, PointEntity | RectangleEntity):
                        references[key] = SketchGeometryReference(entity.entity_id, "vertex", index)
                    else:
                        references[key] = SketchGeometryReference(entity.entity_id, "center")
                if isinstance(entity, LineEntity):
                    midpoint = (
                        (entity.start_mm[0] + entity.end_mm[0]) / 2,
                        (entity.start_mm[1] + entity.end_mm[1]) / 2,
                    )
                    add_anchor(
                        "midpoint", f"{entity.entity_id}:midpoint", plane.local_to_world(midpoint)
                    )
                if isinstance(entity, ArcEntity):
                    for reference_kind, angle in (
                        ("start", entity.start_angle_deg),
                        ("end", entity.start_angle_deg + entity.sweep_angle_deg),
                    ):
                        local_point = (
                            entity.center_mm[0] + entity.radius_mm * cos(radians(angle)),
                            entity.center_mm[1] + entity.radius_mm * sin(radians(angle)),
                        )
                        key = f"{entity.entity_id}:{reference_kind}"
                        add_anchor("vertex", key, plane.local_to_world(local_point))
                        references[key] = SketchGeometryReference(
                            entity.entity_id, cast('Literal["start", "end"]', reference_kind)
                        )
            snap = choose_object_snap(
                anchors, (x, y), plane, allow_projection=self.project_snap.isChecked()
            )
            if snap is not None:
                self._snapped_this_point = True
                self._last_snap_reference = references.get(snap.anchor.key)
                self._snap_marker = (snap.world, snap.anchor.world if snap.projected else None)
                self._viewport.set_position_markers(*self._snap_marker)
                self.status_label.setText("捕捉点（一次投影）" if snap.projected else "捕捉点")
                return snap.uv
        self._viewport.set_position_markers(None)
        return locate_uv(
            plane.world_to_local(point),
            plane,
            numeric=False,
            grid_enabled=self.grid_snap.isChecked() and not bypass,
            spacing=self.grid_spacing.value(),
        ).uv

    def select_tool(self, tool: str) -> None:
        """Select the drawing operation without changing the locked plane."""
        if not self._can_execute():
            for name, button in self._tool_buttons.items():
                button.setChecked(name == self._tool)
            self.status_label.setText("请等待当前操作完成后再切换草图工具。")
            return
        if self._is_current() and tool in (
            "select",
            "point",
            "line",
            "continuous",
            "rectangle",
            "circle",
            "arc",
            "spline",
            "trim",
            "extend",
            "offset",
            "mirror",
        ):
            self._close_dimension_editor()
            self._tool = tool
            self.selected_relation_id = None
            self.selected_dimension_id = None
            for name, button in self._tool_buttons.items():
                button.setChecked(name == tool)
            self._clear_temporary_state()
            self.dynamic_input.configure(tool)
            self.offset_controls.setVisible(tool == "offset")
            self.mirror_keep_source.setVisible(tool == "mirror")
            self._display_sketch(self.session.sketch)
            self._viewport.setFocus()
            self.status_label.setText(
                (
                    "选择并锁定草图平面。"
                    if not self._locked
                    else "选择要修改的区段。"
                    if tool in ("trim", "extend", "offset", "mirror")
                    else "选择绘图点。"
                )
                if tool != "select"
                else "选择对象。"
            )

    def begin_dimension_placement(self, kind: str, _checked: bool = False) -> None:
        """Start selecting geometry and a position for a canvas dimension."""
        if (
            kind not in ("length", "distance", "angle", "radius", "diameter")
            or not self._is_current()
        ):
            return
        if not self._can_execute():
            self.status_label.setText("几何工作线程忙碌，请稍后标注。")
            return
        if not self._locked or self._points or self._drag_start is not None:
            self.status_label.setText("请先锁定平面并完成当前图元，再创建尺寸。")
            return
        if self.constraint_dialog is not None or self.dimension_editor is not None:
            self.status_label.setText("请先完成当前尺寸操作。")
            return
        self.select_tool("select")
        self._dimension_kind = kind
        self._dimension_references.clear()
        self.status_label.setText(
            "选择第一个端点或圆心。"
            if kind == "distance"
            else "选择要标注的直线。"
            if kind in ("length", "angle")
            else "选择要标注的圆或圆弧。"
        )

    def begin_region_selection(self) -> None:
        """Build exact closed-region candidates for display and selection."""
        if not self._is_current():
            return
        if not self._can_execute():
            self.status_label.setText("几何工作线程忙碌，请稍后选择区域。")
            return
        if not self._locked or self._points or self.dimension_editor is not None:
            self.status_label.setText("请先锁定平面并完成当前操作。")
            return
        self.select_tool("select")
        try:
            sketch = self.session.sketch
            displayed = {
                entity.entity_id
                for entity in sketch.entities
                if sketch.layers.get(entity.layer_name).displayed
            }
            self._region_candidates = tuple(
                region
                for region in self._services.kernel.sketch_region_data(sketch)
                if all(
                    identity in displayed
                    for identity in (
                        *region.boundary_entity_ids,
                        *(identity for hole in region.hole_entity_ids for identity in hole),
                    )
                )
            )
        except MycadError as exc:
            self.status_label.setText(f"无法选择区域：{exc}")
            self.status_label.setToolTip(str(exc))
            return
        if not self._region_candidates:
            self.status_label.setText("没有可见的闭合区域；请检查草图图层。")
            return
        self._region_mode = True
        self._region_generation = self.session.generation
        self._viewport.set_draft_sketch_regions(self._region_candidates)
        self.status_label.setText("单击闭合区域；内孔与构造线不属于区域。")

    def _place_dimension_click(self, x: float, y: float, *, bypass: bool) -> None:
        kind = self._dimension_kind
        if kind is None or not self._can_execute():
            return
        required = 2 if kind in ("distance", "angle") else 1
        if len(self._dimension_references) < required:
            reference: SketchGeometryReference | None = None
            if kind == "distance":
                choices: list[tuple[float, SketchGeometryReference]] = []
                for item in self.session.sketch.entities:
                    if not self.session.sketch.layers.get(item.layer_name).displayed:
                        continue
                    for candidate, local in SketchCanvas.entity_point_references(item):
                        screen = self._viewport.project_world_point(
                            self.session.sketch.frame.local_to_world(local)
                        )
                        if screen is not None:
                            distance = dist((x, y), screen)
                            if distance <= 12:
                                choices.append((distance, candidate))
                if choices:
                    reference = min(choices, key=lambda item: item[0])[1]
            else:
                self._select_at(x, y)
                entity = next(
                    (
                        item
                        for item in self.session.sketch.entities
                        if item.entity_id == self.selected_entity_id
                    ),
                    None,
                )
                if kind in ("length", "angle") and isinstance(
                    entity, LineEntity | RectangleEntity | PolylineEntity
                ):
                    reference = self._line_reference_at(entity, x, y)
                elif kind in ("radius", "diameter") and isinstance(
                    entity, CircleEntity | ArcEntity
                ):
                    reference = SketchGeometryReference(entity.entity_id, "geometry")
            if reference is None:
                self.status_label.setText("未找到适用于此尺寸的图元或端点。")
                return
            if reference in self._dimension_references:
                self.status_label.setText("请选择另一个不同的引用。")
                return
            self._dimension_references.append(reference)
            self.status_label.setText(
                "选择第二个引用。"
                if len(self._dimension_references) < required
                else "在画布上选择尺寸标注位置，Esc 取消。"
            )
            return
        point = self._pointer_uv(x, y, bypass=bypass)
        if point is None:
            self.status_label.setText("视线与平面平行，请正视工作平面。")
            return
        references = tuple(self._dimension_references)
        entities = {item.entity_id: item for item in self.session.sketch.entities}
        entity = entities.get(references[0].entity_id)
        self._dimension_kind = None
        self._dimension_references.clear()
        self._viewport.set_position_markers(None)
        self.open_constraint_dialog()
        dialog = self.constraint_dialog
        if dialog is None or entity is None:
            return
        dialog.configure_dimensions(kind, tuple(ref.entity_id for ref in references))
        for reference, combo, index in zip(
            references,
            (dialog.first_reference, dialog.second_reference),
            (dialog.first_index, dialog.second_index),
            strict=False,
        ):
            combo.setCurrentIndex(combo.findData(reference.kind))
            if reference.index is not None:
                index.setValue(reference.index)
        dialog.set_dimension_position(point)
        if kind == "distance":
            first = SketchCanvas.point_for_reference(references[0], entities)
            second = SketchCanvas.point_for_reference(references[1], entities)
            if first is not None and second is not None:
                dialog.value_field.setValue(dist(first, second))
        elif kind == "angle":
            first_line = SketchCanvas.line_for_reference(references[0], entities)
            second_line = SketchCanvas.line_for_reference(references[1], entities)
            if first_line is not None and second_line is not None:
                first_angle = atan2(
                    first_line[1][1] - first_line[0][1], first_line[1][0] - first_line[0][0]
                )
                second_angle = atan2(
                    second_line[1][1] - second_line[0][1], second_line[1][0] - second_line[0][0]
                )
                dialog.value_field.setValue(degrees(second_angle - first_angle) % 360)
        elif kind == "length":
            line = SketchCanvas.line_for_reference(references[0], entities)
            if line is not None:
                dialog.value_field.setValue(dist(*line))
        elif isinstance(entity, CircleEntity | ArcEntity):
            dialog.value_field.setValue(entity.radius_mm * (2 if kind == "diameter" else 1))

    def _line_reference_at(
        self, entity: LineEntity | RectangleEntity | PolylineEntity, x: float, y: float
    ) -> SketchGeometryReference | None:
        if isinstance(entity, LineEntity):
            return SketchGeometryReference(entity.entity_id, "geometry")
        count = (
            4
            if isinstance(entity, RectangleEntity)
            else len(entity.points_mm) - (0 if entity.closed else 1)
        )
        choices: list[tuple[float, SketchGeometryReference]] = []
        for index in range(count):
            reference = SketchGeometryReference(entity.entity_id, "segment", index)
            line = SketchCanvas.line_for_reference(reference, {entity.entity_id: entity})
            if line is None:
                continue
            first = self._viewport.project_world_point(
                self.session.sketch.frame.local_to_world(line[0])
            )
            second = self._viewport.project_world_point(
                self.session.sketch.frame.local_to_world(line[1])
            )
            if first is None or second is None:
                continue
            dx, dy = second[0] - first[0], second[1] - first[1]
            length_sq = dx * dx + dy * dy
            factor = (
                0.0
                if length_sq == 0
                else max(0.0, min(1.0, ((x - first[0]) * dx + (y - first[1]) * dy) / length_sq))
            )
            distance = dist((x, y), (first[0] + factor * dx, first[1] + factor * dy))
            if distance <= 10:
                choices.append((distance, reference))
        return min(choices, key=lambda item: item[0])[1] if choices else None

    def _resolve_line_point(
        self, point: Point2D, *, infer: bool
    ) -> tuple[Point2D, Literal["horizontal", "vertical"] | None]:
        if not self._points or not infer or not self.auto_relations.isChecked():
            return point, None
        start = self._points[0]
        plane = self.session.sketch.frame
        screen = self._viewport.project_world_point(plane.local_to_world(point))
        horizontal = self._viewport.project_world_point(plane.local_to_world((point[0], start[1])))
        vertical = self._viewport.project_world_point(plane.local_to_world((start[0], point[1])))
        if screen is not None and horizontal is not None and vertical is not None:
            h, v = dist(screen, horizontal), dist(screen, vertical)
            if min(h, v) <= 8 and (not self._snapped_this_point or min(h, v) < 1e-6):
                if h <= v:
                    return (point[0], start[1]), "horizontal"
                return (start[0], point[1]), "vertical"
        return point, None

    def _on_dynamic_input_changed(self) -> None:
        if not self._is_current():
            return
        if self._last_dynamic_point is not None and self._points:
            self._preview_drawing(self._last_dynamic_point, infer=self._last_dynamic_infer)

    def _cancel_dynamic_entity(self) -> None:
        if not self._is_current():
            return
        self._clear_temporary_state()
        self._display_sketch(self.session.sketch)
        self.status_label.setText("当前图元已取消。")
        self._viewport.setFocus()

    def _resolve_drawing_point(
        self, point: Point2D, *, infer: bool
    ) -> tuple[Point2D, Literal["horizontal", "vertical"] | None]:
        snapped_point = point
        inferred: Literal["horizontal", "vertical"] | None = None
        if self._tool in ("line", "continuous"):
            point, inferred = self._resolve_line_point(point, infer=infer)
        try:
            resolved = self.dynamic_input.resolve(self._points[0], point)
        except ValueError:
            self._dynamic_input_error = True
            raise
        if self._dynamic_input_error:
            self._dynamic_input_error = False
            self.status_label.setText("选择绘图点。")
        if self._snapped_this_point:
            if dist(snapped_point, resolved) > 1e-9:
                self._viewport.set_position_markers(None)
            elif self._snap_marker is not None:
                self._viewport.set_position_markers(*self._snap_marker)
        if inferred == "horizontal" and abs(resolved[1] - self._points[0][1]) > 1e-9:
            inferred = None
        if inferred == "vertical" and abs(resolved[0] - self._points[0][0]) > 1e-9:
            inferred = None
        return resolved, inferred

    def place_uv(self, point: Point2D, *, numeric: bool = True, infer: bool = True) -> None:
        """Place one exact local point in the active drawing operation."""
        if not self._can_execute():
            self.status_label.setText("请等待当前操作完成后再绘制。")
            return
        if not self._locked or not self._is_current() or self._tool == "select":
            return
        if self._tool == "mirror":
            if self._mirror_target_id is None:
                self.status_label.setText("请先在画布上选择镜像对象。")
            elif self._mirror_axis_start is None:
                self._mirror_axis_start = point
                self.status_label.setText("选择镜像轴的终点。")
            else:
                try:
                    self._commit_mirror(self._mirror_candidate_at(point))
                except ValueError as exc:
                    self.status_label.setText(str(exc))
            return
        if self._tool in ("trim", "extend", "offset"):
            self.status_label.setText("请在画布上单击要修改的区段。")
            return
        self._rubber_band_curve = ()
        if self._tool == "spline":
            self._points.append(point)
            controls = tuple(self._points)
            try:
                outline = (
                    SplineEntity(self.session.sketch.sketch_id, controls).sampled_points()
                    if len(controls) >= 4
                    else controls
                )
            except ValueError:
                outline = controls
            if len(outline) > 1:
                self._rubber_band_curve = tuple(
                    self.session.sketch.frame.local_to_world(item) for item in outline
                )
            self._invalidate_preview()
            self.status_label.setText(
                f"已放置 {len(self._points)} 个控制点；至少四点后按 Enter 完成。"
            )
            return
        if self._tool == "point":
            entity = PointEntity(
                new_sketch_identity(), point, construction=self.construction.isChecked()
            )
            sketch = self.session.sketch
            constraints = sketch.constraints
            if (
                not numeric
                and infer
                and self.auto_relations.isChecked()
                and self._last_snap_reference
            ):
                constraints = (
                    *constraints,
                    SketchConstraint(
                        new_sketch_identity(),
                        "coincident",
                        (
                            SketchGeometryReference(entity.entity_id, "vertex", 0),
                            self._last_snap_reference,
                        ),
                        source="inferred",
                    ),
                )
            self.session.replace_sketch(
                replace(sketch, entities=(*sketch.entities, entity), constraints=constraints)
            )
            self._last_snap_reference = None
            self._viewport.set_position_markers(None)
            self._invalidate_preview()
            self.status_label.setText("点已加入草稿；可继续绘制或预览。")
            return
        if not self._points:
            self._points.append(point)
            self._invalidate_preview()
            self._start_snap_reference = None if numeric else self._last_snap_reference
            return
        if self._tool == "arc" and len(self._points) == 1:
            if dist(self._points[0], point) <= 1e-12:
                self.status_label.setText("圆弧半径必须大于零。")
                return
            self._points.append(point)
            return
        try:
            identity = new_sketch_identity()
            start = self._points[0]
            original_point = point
            point, inferred = self._resolve_drawing_point(point, infer=infer and not numeric)
            if self._tool in ("line", "continuous"):
                entity = LineEntity(
                    identity, start, point, construction=self.construction.isChecked()
                )
            elif self._tool == "rectangle":
                entity = RectangleEntity(
                    identity, start, point, construction=self.construction.isChecked()
                )
            elif self._tool == "circle":
                entity = CircleEntity(
                    identity, start, dist(start, point), construction=self.construction.isChecked()
                )
            else:
                arc_start = self._points[1]
                if dist(start, point) <= 1e-12:
                    raise ValueError("圆弧终点不能与圆心重合。")
                angle = degrees(atan2(arc_start[1] - start[1], arc_start[0] - start[0]))
                end = degrees(atan2(point[1] - start[1], point[0] - start[0]))
                entity = ArcEntity(
                    identity,
                    start,
                    dist(start, arc_start),
                    angle,
                    (end - angle) % 360,
                    construction=self.construction.isChecked(),
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        sketch = self.session.sketch
        constraints = sketch.constraints
        if inferred is not None:
            constraints = (
                *constraints,
                SketchConstraint(
                    new_sketch_identity(),
                    inferred,
                    (SketchGeometryReference(identity, "geometry"),),
                    source="inferred",
                ),
            )
        if isinstance(entity, LineEntity) and self.auto_relations.isChecked() and infer:
            end_reference = (
                None if numeric or dist(original_point, point) > 1e-9 else self._last_snap_reference
            )
            for new_end, target in (("start", self._start_snap_reference), ("end", end_reference)):
                if target is not None:
                    constraints = (
                        *constraints,
                        SketchConstraint(
                            new_sketch_identity(),
                            "coincident",
                            (
                                SketchGeometryReference(
                                    identity, cast('Literal["start", "end"]', new_end)
                                ),
                                target,
                            ),
                            source="inferred",
                        ),
                    )
        self.session.replace_sketch(
            replace(sketch, entities=(*sketch.entities, entity), constraints=constraints)
        )
        self._points = [point] if self._tool == "continuous" else []
        self._start_snap_reference = (
            SketchGeometryReference(identity, "end") if self._tool == "continuous" else None
        )
        self._last_dynamic_point = None
        self.dynamic_input.clear_locks()
        self._snapped_this_point = False
        self._snap_marker = None
        self._last_snap_reference = None
        self._invalidate_preview()
        self.status_label.setText("图元已加入草稿；可继续绘制或预览。")

    def _offset_distance_changed(self, _value: float) -> None:
        self._trim_preview = None
        if self._tool == "offset":
            self._display_sketch(self.session.sketch)

    def _mirror_options_changed(self, _checked: bool) -> None:
        self._trim_preview = None
        if self._tool == "mirror":
            self._display_sketch(self.session.sketch)

    def _visible_entity_at(self, x: float, y: float) -> str:
        sketch = self.session.sketch
        point_id = self._viewport.draft_sketch_point_at(x, y)
        if point_id is not None:
            return point_id
        visible_ids = {
            entity.entity_id
            for entity in sketch.entities
            if sketch.layers.get(entity.layer_name).displayed
        }
        candidates: dict[str, float] = {}
        for identity, curve in self._rendered_curves:
            if identity not in visible_ids:
                continue
            projected = tuple(self._viewport.project_world_point(item) for item in curve)
            for first, second in zip(projected, projected[1:], strict=False):
                if first is None or second is None:
                    continue
                dx, dy = second[0] - first[0], second[1] - first[1]
                square = dx * dx + dy * dy
                factor = (
                    0.0
                    if square == 0
                    else max(0.0, min(1.0, ((x - first[0]) * dx + (y - first[1]) * dy) / square))
                )
                distance = dist((x, y), (first[0] + factor * dx, first[1] + factor * dy))
                if distance <= 10:
                    candidates[identity] = min(distance, candidates.get(identity, distance))
        ranked = sorted((distance, identity) for identity, distance in candidates.items())
        if not ranked:
            raise ValueError("请选择可见的草图图元。")
        if len(ranked) > 1 and ranked[1][0] - ranked[0][0] < 1:
            raise ValueError("目标不明确；请放大或分开重叠曲线。")
        return ranked[0][1]

    def _mirror_candidate(self, x: float, y: float) -> Sketch:
        end = self._pointer_uv(x, y, bypass=True)
        if end is None:
            raise ValueError("视线与平面平行，请正视工作平面。")
        return self._mirror_candidate_at(end)

    def _mirror_candidate_at(self, end: Point2D) -> Sketch:
        sketch = self.session.sketch
        identity = self._mirror_target_id
        start = self._mirror_axis_start
        if identity is None or start is None:
            raise ValueError("请选择镜像对象和轴线。")
        target = next((entity for entity in sketch.entities if entity.entity_id == identity), None)
        if target is None or self._mirror_generation != self.session.generation:
            raise ValueError("镜像对象已改变，请重新选择。")
        if sketch.layers.get(target.layer_name).locked:
            raise ValueError("锁定图层上的图元不能镜像。")
        entities = sketch.entities
        if self.mirror_keep_source.isChecked():
            source_ids = {entity.entity_id for entity in entities}
            entities = copy_entities(entities, (identity,), (0, 0))
            selected = tuple(
                entity.entity_id for entity in entities if entity.entity_id not in source_ids
            )
        else:
            if any(
                ref.entity_id == identity
                for constraint in sketch.constraints
                for ref in constraint.references
            ):
                raise ValueError("镜像目标存在关联尺寸或关系；请保留原件或先删除关联。")
            selected = (identity,)
        return replace(sketch, entities=mirror_entities(entities, selected, start, end))

    def _commit_mirror(self, candidate: Sketch) -> None:
        self.session.replace_sketch(candidate)
        self._mirror_target_id = None
        self._mirror_axis_start = None
        self._mirror_generation = None
        self._trim_preview = None
        self._rubber_band_curve = ()
        self._invalidate_preview()
        self.status_label.setText("镜像已加入草稿；可继续操作或撤销。")

    def _curve_edit_candidate(self, x: float, y: float) -> Sketch:
        sketch = self.session.sketch
        point = self._pointer_uv(x, y, bypass=True)
        offset = self._pointer_uv(x + 10, y, bypass=True)
        if point is None or offset is None:
            raise ValueError("视线与平面平行，请正视工作平面。")
        visible = tuple(
            entity for entity in sketch.entities if sketch.layers.get(entity.layer_name).displayed
        )
        for entity in visible:
            if not isinstance(entity, SplineEntity):
                continue
            projected = tuple(
                self._viewport.project_world_point(sketch.frame.local_to_world(sample))
                for sample in entity.sampled_points()
            )
            for first, second in zip(projected, projected[1:], strict=False):
                if first is None or second is None:
                    continue
                dx, dy = second[0] - first[0], second[1] - first[1]
                square = dx * dx + dy * dy
                factor = (
                    0.0
                    if square == 0
                    else max(0.0, min(1.0, ((x - first[0]) * dx + (y - first[1]) * dy) / square))
                )
                if dist((x, y), (first[0] + factor * dx, first[1] + factor * dy)) <= 8:
                    raise ValueError("样条暂不支持修剪、延伸或偏移；草稿未修改。")
        if self._tool == "offset":
            if self._viewport.draft_sketch_point_at(x, y) is not None:
                raise ValueError("点不支持偏移；草稿未修改。")
            visible_by_id = {entity.entity_id: entity for entity in visible}
            identity = self._visible_entity_at(x, y)
            if sketch.layers.get(visible_by_id[identity].layer_name).locked:
                raise ValueError("锁定图层上的图元不能偏移。")
            return replace(
                sketch,
                entities=offset_entities(
                    sketch.entities, (identity,), self.offset_distance.value()
                ),
            )
        tolerance = max(dist(point, offset), 1e-9)
        changed = (
            trim_curve_at(
                visible, point, hit_tolerance_mm=tolerance, allow_endpoint_intersections=True
            )
            if self._tool == "trim"
            else extend_curve_at(visible, point, hit_tolerance_mm=tolerance)
        )
        old_by_id = {entity.entity_id: entity for entity in visible}
        new_by_id = {entity.entity_id: entity for entity in changed}
        altered = {
            identity for identity, entity in old_by_id.items() if new_by_id.get(identity) != entity
        }
        if any(sketch.layers.get(old_by_id[identity].layer_name).locked for identity in altered):
            raise ValueError("锁定图层上的图元不能修改。")
        if any(
            reference.entity_id in altered
            for constraint in sketch.constraints
            for reference in constraint.references
        ):
            raise ValueError("目标存在关联尺寸或关系；请先删除关联后再修改。")
        hidden_before: dict[str, list[SketchEntity]] = {}
        trailing: list[SketchEntity] = []
        for index, entity in enumerate(sketch.entities):
            if sketch.layers.get(entity.layer_name).displayed:
                continue
            successor = next(
                (
                    candidate.entity_id
                    for candidate in sketch.entities[index + 1 :]
                    if sketch.layers.get(candidate.layer_name).displayed
                    and candidate.entity_id in new_by_id
                ),
                None,
            )
            (hidden_before.setdefault(successor, []) if successor else trailing).append(entity)
        merged: list[SketchEntity] = []
        for entity in changed:
            merged.extend(hidden_before.pop(entity.entity_id, ()))
            merged.append(entity)
        for remaining in hidden_before.values():
            merged.extend(remaining)
        merged.extend(trailing)
        return replace(sketch, entities=tuple(merged))

    def finish_spline(self) -> None:
        if not self._can_execute():
            self.status_label.setText("请等待当前操作完成后再完成样条。")
            return
        if len(self._points) < 4:
            self.status_label.setText("三次样条至少需要四个控制点；继续放置或按 Esc 取消。")
            return
        try:
            entity = SplineEntity(
                new_sketch_identity(),
                tuple(self._points),
                construction=self.construction.isChecked(),
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        sketch = self.session.sketch
        self.session.replace_sketch(replace(sketch, entities=(*sketch.entities, entity)))
        self._points.clear()
        self._rubber_band_curve = ()
        self._invalidate_preview()
        self.status_label.setText("样条已加入草稿；可继续绘制或预览。")

    def _invalidate_preview(self) -> None:
        if (
            self._mirror_generation is not None
            and self._mirror_generation != self.session.generation
        ):
            self._mirror_target_id = None
            self._mirror_axis_start = None
            self._mirror_generation = None
            self._trim_preview = None
            self._rubber_band_curve = ()
        if (
            self._region_generation is not None
            and self._region_generation != self.session.generation
        ):
            self._clear_temporary_state()
        self._preview_generation = None
        self._selection_only_preview = False
        self.confirm_button.setEnabled(False)
        self._viewport.clear_candidate_preview()
        self._display_sketch(self.session.sketch)

    def _display_sketch(self, sketch: Sketch) -> None:
        if self._closed or self._current_session() != self._session_identity:
            return
        self._displayed_sketch = sketch
        curves: list[tuple[str, tuple[tuple[float, float, float], ...]]] = []
        draft_points: list[tuple[str, Point3D]] = []
        for entity in sketch.entities:
            if not sketch.layers.get(entity.layer_name).displayed:
                continue
            if isinstance(entity, PointEntity):
                draft_points.append(
                    (entity.entity_id, sketch.frame.local_to_world(entity.position_mm))
                )
                continue
            if isinstance(entity, LineEntity):
                points = (entity.start_mm, entity.end_mm)
            elif isinstance(entity, RectangleEntity):
                u1, v1 = entity.first_corner_mm
                u2, v2 = entity.opposite_corner_mm
                points = ((u1, v1), (u2, v1), (u2, v2), (u1, v2), (u1, v1))
            elif isinstance(entity, PolylineEntity):
                points = polyline_sampled_points(entity)
            elif isinstance(entity, SplineEntity):
                points = entity.sampled_points()
            else:
                start = 0.0 if isinstance(entity, CircleEntity) else entity.start_angle_deg
                sweep = 360.0 if isinstance(entity, CircleEntity) else entity.sweep_angle_deg
                points = tuple(
                    (
                        entity.center_mm[0]
                        + entity.radius_mm * cos(radians(start + sweep * i / 48)),
                        entity.center_mm[1]
                        + entity.radius_mm * sin(radians(start + sweep * i / 48)),
                    )
                    for i in range(49)
                )
            curves.append((entity.entity_id, tuple(sketch.frame.local_to_world(p) for p in points)))
        self._rendered_curves = curves.copy()
        self._viewport.set_draft_sketch_points(
            tuple(draft_points), selected_id=self.selected_entity_id
        )
        selected_spline = next(
            (
                entity
                for entity in sketch.entities
                if isinstance(entity, SplineEntity)
                and self._tool == "select"
                and entity.entity_id == self.selected_entity_id
                and sketch.layers.get(entity.layer_name).displayed
            ),
            None,
        )
        self._viewport.set_draft_sketch_control_points(
            tuple(sketch.frame.local_to_world(point) for point in selected_spline.control_points_mm)
            if selected_spline is not None
            else ()
        )
        if self._rubber_band_curve:
            curves.append(("__rubber_band__", self._rubber_band_curve))
        selected_index = next(
            (
                index
                for index, (identity, _) in enumerate(curves)
                if identity == self.selected_entity_id
            ),
            None,
        )
        self._viewport.set_draft_sketch_curves(
            tuple(points for _, points in curves),
            selected_index=selected_index,
            construction_indices=frozenset(
                index
                for index, (identity, _) in enumerate(curves)
                if any(
                    entity.entity_id == identity and entity.construction
                    for entity in sketch.entities
                )
            ),
        )
        labels: list[DraftRelationAnnotation] = []
        symbols = {
            "horizontal": "H",
            "vertical": "V",
            "coincident": "●",
            "parallel": "∥",
            "perpendicular": "⟂",
            "tangent": "T",
            "concentric": "◎",
            "equal": "=",
            "fixed": "F",
        }
        for relation in sketch.constraints:
            symbol = symbols.get(relation.kind)
            if symbol is None:
                continue
            reference = relation.references[0]
            curve = next(
                (points for identity, points in curves if identity == reference.entity_id), ()
            )
            if curve:
                point = (
                    curve[0]
                    if reference.kind == "start"
                    else curve[-1]
                    if reference.kind == "end"
                    else curve[len(curve) // 2]
                )
                if reference.kind == "geometry" and len(curve) == 2:
                    point = (
                        (curve[0][0] + curve[1][0]) / 2,
                        (curve[0][1] + curve[1][1]) / 2,
                        (curve[0][2] + curve[1][2]) / 2,
                    )
                text = (
                    f"[{symbol}]" if relation.constraint_id == self.selected_relation_id else symbol
                )
                labels.append(DraftRelationAnnotation(relation.constraint_id, point, text))
        self._viewport.set_draft_relation_annotations(tuple(labels))
        dimensions = tuple(
            replace(item, color_rgb=(220, 112, 20))
            if item.constraint_id == self.selected_dimension_id
            else item
            for item in draft_dimensions(sketch)
        )
        self._viewport.set_draft_sketch_dimensions(dimensions)
        self._viewport.set_draft_dimension_leaders(draft_dimension_leaders(sketch, dimensions))

    def _preview_drawing(self, point: Point2D, *, infer: bool = True) -> None:
        """Show a disposable outline for the in-progress drawing operation."""
        if not self._points:
            return
        self._last_dynamic_point = point
        self._last_dynamic_infer = infer
        start = self._points[0]
        try:
            point, _ = self._resolve_drawing_point(point, infer=infer)
        except ValueError as exc:
            self._rubber_band_curve = ()
            self._display_sketch(self.session.sketch)
            self.status_label.setText(str(exc))
            return
        self.dynamic_input.update_from_pointer(start, point)
        if self._tool == "spline":
            controls = (*self._points, point)
            try:
                points = (
                    SplineEntity(self.session.sketch.sketch_id, controls).sampled_points()
                    if len(controls) >= 4
                    else controls
                )
            except ValueError:
                points = controls
        elif self._tool in ("line", "continuous"):
            points = (start, point)
        elif self._tool == "rectangle":
            points = (start, (point[0], start[1]), point, (start[0], point[1]), start)
        elif self._tool == "circle":
            radius = dist(start, point)
            points = tuple(
                (
                    start[0] + radius * cos(radians(i * 7.5)),
                    start[1] + radius * sin(radians(i * 7.5)),
                )
                for i in range(49)
            )
        elif self._tool == "arc" and len(self._points) > 1:
            radius = dist(start, self._points[1])
            angle = degrees(atan2(self._points[1][1] - start[1], self._points[1][0] - start[0]))
            end = degrees(atan2(point[1] - start[1], point[0] - start[0]))
            sweep = (end - angle) % 360
            points = tuple(
                (
                    start[0] + radius * cos(radians(angle + sweep * i / 48)),
                    start[1] + radius * sin(radians(angle + sweep * i / 48)),
                )
                for i in range(49)
            )
        else:
            points = (start, point)
        self._rubber_band_curve = tuple(self.session.sketch.frame.local_to_world(p) for p in points)
        self._display_sketch(self.session.sketch)

    def toggle_selected_construction(self) -> None:
        """Switch the selected entity between profile and construction geometry."""
        if not self._can_execute():
            self.status_label.setText("请等待当前操作完成后再修改草图。")
            return
        selected = self.selected_entity_id
        if not self._is_current() or selected is None:
            return
        sketch = self.session.sketch
        entities = tuple(
            replace(entity, construction=not entity.construction)
            if entity.entity_id == selected
            else entity
            for entity in sketch.entities
        )
        self.session.replace_sketch(replace(sketch, entities=entities))
        self._invalidate_preview()

    def _select_at(self, x: float, y: float) -> None:
        self.selected_relation_id = None
        self.selected_dimension_id = None
        if self.selected_entity_id is not None and any(
            screen is not None and dist((x, y), screen) <= 10
            for point in self._viewport.draft_sketch_control_points()
            for screen in (self._viewport.project_world_point(point),)
        ):
            return
        choices: list[tuple[float, str]] = []
        point_id = self._viewport.draft_sketch_point_at(x, y)
        if point_id is not None:
            choices.append((0.0, point_id))
        for identity, curve in self._rendered_curves:
            screen = tuple(self._viewport.project_world_point(point) for point in curve)
            for first, second in zip(screen, screen[1:], strict=False):
                if first is None or second is None:
                    continue
                dx, dy = second[0] - first[0], second[1] - first[1]
                length_sq = dx * dx + dy * dy
                factor = (
                    0.0
                    if length_sq == 0
                    else max(0.0, min(1.0, ((x - first[0]) * dx + (y - first[1]) * dy) / length_sq))
                )
                distance = dist((x, y), (first[0] + factor * dx, first[1] + factor * dy))
                if distance <= 10:
                    choices.append((distance, identity))
        by_identity: dict[str, float] = {}
        for distance, identity in choices:
            by_identity[identity] = min(distance, by_identity.get(identity, distance))
        candidates = sorted(by_identity, key=lambda identity: (by_identity[identity], identity))
        if candidates:
            cycle = (
                self._selection_point is not None
                and dist(self._selection_point, (x, y)) <= 4
                and self.selected_entity_id in candidates
            )
            selected = self.selected_entity_id
            index = (candidates.index(selected) + 1) % len(candidates) if cycle and selected else 0
            self.selected_entity_id = candidates[index]
            if len(candidates) > 1:
                self.status_label.setText(f"重叠候选 {index + 1}/{len(candidates)}；再次单击切换。")
        else:
            self.selected_entity_id = None
        self._selection_point = (x, y)
        self._invalidate_preview()

    def delete_selection(self) -> None:
        """Delete the selected draft entity and its related constraints locally."""
        if not self._can_execute():
            self.status_label.setText("请等待当前操作完成后再删除草图对象。")
            return
        if self._is_current() and self.selected_relation_id is not None:
            identity = self.selected_relation_id
            sketch = self.session.sketch
            self.session.replace_sketch(
                replace(
                    sketch,
                    constraints=tuple(
                        item for item in sketch.constraints if item.constraint_id != identity
                    ),
                )
            )
            self.selected_relation_id = None
            self._invalidate_preview()
            self.status_label.setText("关系已删除，可撤销。")
            return
        if self._is_current() and self.selected_entity_id is not None:
            affected = tuple(
                constraint
                for constraint in self.session.sketch.constraints
                if any(ref.entity_id == self.selected_entity_id for ref in constraint.references)
            )
            if affected:
                details = "\n".join(f"{item.kind} · {item.constraint_id}" for item in affected)
                answer = QMessageBox.question(
                    self,
                    "删除关联图元",
                    f"删除图元将同时删除以下关系：\n{details}\n\n是否继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            removed = self.session.delete_entities((self.selected_entity_id,))
            self.selected_entity_id = None
            self._invalidate_preview()
            self.status_label.setText(f"已删除图元及 {len(removed)} 条关联。")

    def _begin_drag(self, x: float, y: float) -> None:
        self._drag_reference = None
        self._drag_start = (x, y)
        choices: list[tuple[float, str, SketchGeometryReference]] = []
        for entity in self.session.sketch.entities:
            if not self.session.sketch.layers.get(entity.layer_name).displayed:
                continue
            handles: list[tuple[SketchGeometryReference, Point2D]] = []
            if isinstance(entity, PointEntity):
                handles = [
                    (SketchGeometryReference(entity.entity_id, "vertex", 0), entity.position_mm)
                ]
            elif isinstance(entity, LineEntity):
                handles = [
                    (SketchGeometryReference(entity.entity_id, "start"), entity.start_mm),
                    (SketchGeometryReference(entity.entity_id, "end"), entity.end_mm),
                ]
            elif isinstance(entity, RectangleEntity):
                u1, v1 = entity.first_corner_mm
                u2, v2 = entity.opposite_corner_mm
                handles = [
                    (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                    for index, point in enumerate(((u1, v1), (u2, v1), (u2, v2), (u1, v2)))
                ]
            elif isinstance(entity, (CircleEntity, ArcEntity)):
                handles = [(SketchGeometryReference(entity.entity_id, "center"), entity.center_mm)]
                if isinstance(entity, ArcEntity):
                    for kind, angle in (
                        ("start", entity.start_angle_deg),
                        ("end", entity.start_angle_deg + entity.sweep_angle_deg),
                    ):
                        handles.append(
                            (
                                SketchGeometryReference(
                                    entity.entity_id, cast('Literal["start", "end"]', kind)
                                ),
                                (
                                    entity.center_mm[0] + entity.radius_mm * cos(radians(angle)),
                                    entity.center_mm[1] + entity.radius_mm * sin(radians(angle)),
                                ),
                            )
                        )
            else:
                points = (
                    entity.points_mm
                    if isinstance(entity, PolylineEntity)
                    else entity.control_points_mm
                )
                handles = [
                    (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                    for index, point in enumerate(points)
                ]
            for reference, local in handles:
                screen = self._viewport.project_world_point(
                    self.session.sketch.frame.local_to_world(local)
                )
                if screen is not None:
                    distance = dist((x, y), screen)
                    if distance <= 10:
                        choices.append(
                            (
                                distance,
                                f"{entity.entity_id}:{reference.kind}:{reference.index}",
                                reference,
                            )
                        )
        if choices:
            self._drag_reference = min(
                choices,
                key=lambda choice: (
                    choice[2].entity_id != self.selected_entity_id,
                    choice[0],
                    choice[1],
                ),
            )[2]
            self.selected_entity_id = self._drag_reference.entity_id
            self._invalidate_preview()

    def _drag_result(self, x: float, y: float, *, bypass: bool) -> Sketch | None:
        reference, start = self._drag_reference, self._drag_start
        if reference is None or start is None or dist(start, (x, y)) < 3:
            return None
        uv = self._pointer_uv(x, y, bypass=bypass)
        if uv is None:
            self.status_label.setText("视线与平面平行，请正视工作平面。")
            return None
        sketch = self.session.sketch
        try:
            if sketch.constraints:
                result = self._services.kernel.preview_sketch_drag(sketch, reference, uv)
                if result.status != "success" or result.sketch is None:
                    raise ValueError(result.message or "拖动求解失败")
                if result.branch_changes:
                    raise ValueError("拖动可能改变求解分支，请使用尺寸编辑并确认。")
                edited = result.sketch
            else:
                edited = replace(
                    sketch, entities=move_sketch_handle(sketch.entities, reference, uv)
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return None
        return edited

    def _finish_drag(self, x: float, y: float, *, bypass: bool) -> None:
        edited = self._drag_result(x, y, bypass=bypass)
        self._drag_reference = None
        self._drag_start = None
        if edited is not None:
            self.session.replace_sketch(edited)
        self._invalidate_preview()

    def _clear_temporary_state(self) -> None:
        self._trim_preview = None
        self._mirror_target_id = None
        self._mirror_axis_start = None
        self._mirror_generation = None
        if self._selection_only_preview:
            self._selection_only_preview = False
            self._preview_generation = None
            self.confirm_button.setEnabled(False)
        self._region_mode = False
        self._region_generation = None
        self._region_candidates = ()
        self._hovered_region = None
        self.selected_region_ids = None
        self._viewport.set_draft_sketch_regions(())
        self._points.clear()
        self._last_dynamic_point = None
        self._dynamic_input_error = False
        self.dynamic_input.clear_locks()
        self._snapped_this_point = False
        self._snap_marker = None
        self._last_snap_reference = None
        self._dimension_kind = None
        self._dimension_references.clear()
        self._rubber_band_curve = ()
        self._start_snap_reference = None
        self._drag_reference = None
        self._drag_start = None
        self._viewport.set_position_markers(None)

    def undo(self) -> None:
        """Undo one accepted local edit without altering the document."""
        if not self._can_execute():
            self.status_label.setText("请等待当前操作完成后再撤销。")
            return
        if self._is_current():
            self.session.undo()
            self._clear_temporary_state()
            self._invalidate_preview()

    def redo(self) -> None:
        """Restore one local draft edit."""
        if not self._can_execute():
            self.status_label.setText("请等待当前操作完成后再重做。")
            return
        if self._is_current():
            self.session.redo()
            self._clear_temporary_state()
            self._invalidate_preview()

    def open_constraint_dialog(self) -> None:
        """Solve one explicit dimension or relation against the current draft."""
        if not self._can_execute():
            self.status_label.setText("请等待当前操作完成后再编辑草图约束。")
            return
        if not self._is_current() or not self.session.sketch.entities:
            return
        if self.constraint_dialog is not None:
            self.constraint_dialog.raise_()
            return
        dialog = SketchConstraintDialog(
            (self.session.sketch,),
            self._services.kernel.preview_sketch_constraint,
            self,
            preview_update=self._services.kernel.preview_sketch_constraint_update,
        )
        self.constraint_dialog = dialog

        def apply(
            sketch: Sketch, constraint: SketchConstraint, result: SketchConstraintSolveResult
        ) -> None:
            try:
                self.accept_constraint(sketch, constraint, result)
            except ValueError as exc:
                dialog.submission_failed(str(exc), invalidate_preview=True)
                return
            dialog.accept()

        def closed(_result: int) -> None:
            if self.constraint_dialog is dialog:
                self.constraint_dialog = None
            if self._is_current():
                self._display_sketch(self.session.sketch)

        def display_solve(result: object) -> None:
            if not self._is_current():
                return
            if isinstance(result, SketchConstraintSolveResult) and result.sketch is not None:
                self._display_sketch(result.sketch)
            else:
                self._display_sketch(self.session.sketch)

        def restore_draft() -> None:
            if self._is_current():
                self._display_sketch(self.session.sketch)

        dialog.commit_requested.connect(apply)
        dialog.preview_invalidated.connect(restore_draft)
        dialog.solved_preview.connect(display_solve)
        dialog.finished.connect(closed)
        dialog.open()

    def _close_dimension_editor(self) -> None:
        editor = self.dimension_editor
        self.dimension_editor = None
        if editor is not None:
            editor.hide()
            editor.deleteLater()
            self._viewport.setFocus()

    def _edit_dimension_at(self, identity: str, position: QPoint) -> None:
        if not self._can_execute():
            self.status_label.setText("几何工作线程忙碌，请稍后修改尺寸。")
            return
        constraint = next(
            (item for item in self.session.sketch.constraints if item.constraint_id == identity),
            None,
        )
        if constraint is None or constraint.value is None:
            return
        if not constraint.driving:
            self.status_label.setText("参考尺寸由几何测量，不能直接修改。")
            return
        self._close_dimension_editor()
        self._invalidate_preview()
        editor = _DimensionEditor(self._viewport)
        self.dimension_editor = editor
        editor.setDecimals(max(6, constraint.precision))
        editor.setRange(-1e9, 1e9)
        editor.setSuffix(" °" if constraint.unit == "deg" else " mm")
        editor.setValue(constraint.value)
        editor.setAccessibleName("修改驱动尺寸")
        editor.resize(150, editor.sizeHint().height())
        editor.move(
            max(0, min(position.x(), self._viewport.width() - editor.width())),
            max(0, min(position.y(), self._viewport.height() - editor.height())),
        )

        def apply() -> None:
            if self.dimension_editor is not editor or not self._is_current():
                return
            if not self._can_execute():
                self.status_label.setText("几何工作线程忙碌，请稍后修改尺寸。")
                return
            try:
                if not editor.hasAcceptableInput():
                    raise ValueError("请输入有效的尺寸。")
                editor.interpretText()
                revised = replace(constraint, value=editor.value())
                sketch = self.session.sketch
                result = self._services.kernel.preview_sketch_constraint_update(sketch, revised)
                if result.status != "success" or result.sketch is None:
                    conflicts = tuple(
                        item
                        for item in sketch.constraints
                        if item.constraint_id in result.conflicting_constraint_ids
                    )
                    identities = tuple(
                        dict.fromkeys(
                            ref.entity_id for item in conflicts for ref in item.references
                        )
                    )
                    if identities:
                        self.selected_entity_id = identities[0]
                        self._display_sketch(sketch)
                    details = "、".join(
                        [
                            *(item.constraint_id[:8] for item in conflicts),
                            *(item[:8] for item in identities),
                        ]
                    )
                    suffix = f"；相关关系/图元：{details}" if details else ""
                    self.status_label.setText(
                        f"尺寸修改失败：{result.message or '求解失败'}{suffix}"
                    )
                    return
                if result.branch_changes:
                    self._close_dimension_editor()
                    self.open_constraint_dialog()
                    dialog = self.constraint_dialog
                    if dialog is not None:
                        index = dialog.dimension_combo.findData(identity)
                        if index >= 0:
                            dialog.dimension_combo.setCurrentIndex(index)
                            dialog.value_field.setValue(revised.value or 0.0)
                            dialog.preview_button.click()
                    self.status_label.setText("求解分支发生变化，请在约束窗口核对并确认。")
                    return
                self.accept_constraint(sketch, revised, result)
            except (MycadError, ValueError) as exc:
                self.status_label.setText(f"尺寸修改失败：{exc}")
                return
            self._close_dimension_editor()

        editor.lineEdit().returnPressed.connect(apply)
        editor.escape_pressed.connect(self._close_dimension_editor)
        editor.show()
        editor.setFocus()
        editor.selectAll()

    def accept_constraint(
        self, sketch: Sketch, constraint: SketchConstraint, result: SketchConstraintSolveResult
    ) -> None:
        """Accept one explicitly confirmed solver result into the local draft."""
        if not self._can_execute():
            raise ValueError("请等待当前操作完成后再确认草图约束。")
        if not self._is_current() or sketch != self.session.sketch:
            raise ValueError("草图已变化，请重新预览约束。")
        if result.status != "success" or result.sketch is None:
            raise ValueError(result.message or "约束求解未成功。")
        if not any(
            item.constraint_id == constraint.constraint_id for item in result.sketch.constraints
        ):
            raise ValueError("求解结果不包含该约束。")
        self.session.replace_sketch(result.sketch)
        self._constraint_edits.append((sketch, constraint, result))
        self._invalidate_preview()
        freedom = "未知" if result.degrees_of_freedom is None else str(result.degrees_of_freedom)
        self.status_label.setText(f"约束已确认到草稿；剩余自由度 {freedom}。完成草图时单独记录。")

    def _parameters(self, sketch: Sketch) -> tuple[int, dict[str, object]]:
        params = sketch.to_state_mapping()
        has_points = any(isinstance(entity, PointEntity) for entity in sketch.entities)
        has_curves = any(
            isinstance(entity, PolylineEntity) and entity.bulges for entity in sketch.entities
        )
        has_relations = any(
            item.kind in ("parallel", "perpendicular", "concentric", "equal", "fixed")
            or (
                item.source == "user"
                and item.kind in ("horizontal", "vertical", "coincident", "tangent")
            )
            for item in sketch.constraints
        )
        has_tangency = any(item.kind == "tangent" for item in sketch.constraints)
        has_endpoints = any(
            item.first_endpoint or item.second_endpoint for item in sketch.constraints
        )
        has_text = any(item.text_override is not None for item in sketch.constraints)
        has_style = any(item.style_name is not None for item in sketch.constraints)
        has_axis = any(item.projection_axis is not None for item in sketch.constraints)
        if self._support is None:
            return (
                32
                if has_style
                else 30
                if has_text
                else 28
                if has_axis
                else 13
                if has_endpoints
                else 9
                if has_relations
                else 8
                if has_curves
                else 6
                if has_tangency
                else 5
                if has_points
                else 3
            ), params
        params.pop("frame")
        params["support"] = {
            "plane": self._support.to_mapping(),
            "offset_uv_mm": [0, 0],
            "rotation_deg": 0,
            "flip_normal": False,
        }
        return (
            32
            if has_style
            else 30
            if has_text
            else 28
            if has_axis
            else 13
            if has_endpoints
            else 9
            if has_relations
            else 8
            if has_curves
            else 6
            if has_tangency
            else 5
            if has_points
            else 4
        ), params

    def preview(self) -> None:
        """Replay the draft in an isolated candidate without writing the document."""
        if not self._can_execute():
            self.status_label.setText("请等待当前操作完成后再预览草图。")
            return
        self.confirm_button.setEnabled(False)
        self._preview_generation = None
        self._selection_only_preview = False
        if self.dimension_editor is not None:
            self.status_label.setText("请先确认尺寸输入或按 Esc 取消，再预览草图。")
            return
        if self._dimension_kind is not None:
            self.status_label.setText("请先完成或取消画布标注，再预览草图。")
            return
        if self._mirror_target_id is not None:
            self.status_label.setText("请先完成或取消镜像，再预览草图。")
            return
        if self._points or self._drag_start is not None:
            self.status_label.setText("请先完成当前图元或按 Esc 取消，再预览草图。")
            return
        if not self._is_current() or not self._locked or not self.session.sketch.entities:
            self.status_label.setText("草稿为空或所属文档已变化。")
            return
        if (
            self._original_sketch is not None
            and self.session.sketch == self._original_sketch
            and self.selected_region_ids is not None
        ):
            self._selection_only_preview = True
            self._preview_generation = self.session.generation
            self.confirm_button.setEnabled(True)
            self.status_label.setText("区域已选择；完成后可用于建模，草图历史保持不变。")
            return
        try:
            final = self.session.sketch
            original = self._original_sketch
            states = self.session.states
            edits: list[tuple[Sketch, Sketch, SketchConstraint, SketchConstraintSolveResult]] = []
            for before, after in zip(states, states[1:], strict=False):
                match = next(
                    (
                        (constraint, solved)
                        for source, constraint, solved in reversed(self._constraint_edits)
                        if source == before and solved.sketch == after
                    ),
                    None,
                )
                if match is not None:
                    edits.append((before, after, *match))

            commands: list[ReplayAppend] = []
            if original is None:
                current = edits[0][0] if edits else final
                version, params = self._parameters(current)
                commands.append(ReplayAppend("sketch.create", version, params, "local"))
            else:
                if final == original:
                    raise ValueError("草图没有修改。")
                current = original
                version = 4

            def revise(before: Sketch, after: Sketch) -> None:
                if before == after:
                    return
                frozen = after.to_state_mapping()
                commands.append(
                    ReplayAppend(
                        "sketch.revise",
                        8
                        if any(c.style_name is not None for c in after.constraints)
                        else 7
                        if any(c.text_override is not None for c in after.constraints)
                        else 5
                        if any(c.projection_axis is not None for c in after.constraints)
                        else 4
                        if any(c.first_endpoint or c.second_endpoint for c in after.constraints)
                        else 3
                        if any(
                            isinstance(entity, PolylineEntity) and entity.bulges
                            for entity in after.entities
                        )
                        else 2
                        if any(isinstance(entity, PointEntity) for entity in after.entities)
                        else 1,
                        {
                            "sketch_id": after.sketch_id,
                            "base_state_sha256": before.local_state_digest(),
                            "entities": frozen["entities"],
                            "constraints": frozen["constraints"],
                        },
                        "local",
                    )
                )

            for before, after, constraint, solved in edits:
                revise(current, before)
                updating = any(
                    item.constraint_id == constraint.constraint_id for item in before.constraints
                )
                commands.append(
                    ReplayAppend(
                        "sketch.constraint.update" if updating else "sketch.constraint.add",
                        (6 if updating else 8)
                        if constraint.style_name is not None
                        else (5 if updating else 7)
                        if constraint.text_override is not None
                        else (4 if updating else 6)
                        if constraint.projection_axis is not None
                        else (2 if updating else 4),
                        solved.command_params(before, constraint, local_frame=True),
                        "local",
                    )
                )
                current = after
            revise(current, final)
            changes = ReplayChangeSet(
                (),
                tuple(commands),
                False,
                6
                if (version >= 4 or final.constraints or len(commands) > 1)
                and self._loaded.document.archive_version < 6
                else None,
            )
            self._candidate.stage(changes, current_session_identity=self._current_session())
            result = self._candidate.preview(current_session_identity=self._current_session())
            if result.scene is None:
                failure = result.failure
                if failure is not None:
                    raise ValueError(
                        f"第 {failure.ordinal + 1} 条命令 {failure.command_id}：{failure.reason}"
                    )
                raise ValueError(f"候选状态：{result.state}")
            scene = result.scene
            self._viewport.show_interaction_scene(
                scene,
                session_identity=self._session_identity,
                is_current=lambda: self._candidate.is_scene_current(
                    scene, current_session_identity=self._current_session()
                ),
            )
            self._viewport.set_draft_sketch_curves(())
            self._viewport.set_draft_sketch_points(())
            self._viewport.set_draft_sketch_control_points(())
            self._viewport.set_draft_relation_labels(())
            self._viewport.set_draft_sketch_dimensions(())
            self._viewport.set_draft_sketch_regions(())
            self._preview_generation = self.session.generation
            self.confirm_button.setEnabled(True)
            self.status_label.setText("预览成功；确认后提交草图。")
        except (MycadError, ValueError) as exc:
            self._viewport.clear_candidate_preview()
            self._invalidate_preview()
            self.status_label.setText(f"预览失败：{exc}")

    def confirm(self) -> None:
        """Commit exactly the current successfully previewed candidate."""
        if not self._can_execute():
            self.status_label.setText("请等待当前操作完成后再确认草图。")
            return
        if (
            not self._is_current()
            or self.dimension_editor is not None
            or bool(self._points)
            or self._drag_start is not None
            or (self._selection_only_preview and self.selected_region_ids is None)
            or not self.confirm_button.isEnabled()
            or self._preview_generation != self.session.generation
        ):
            return
        if self._selection_only_preview:
            self._finished = True
            self.accept()
            return
        try:
            grant = self._candidate.authorize_commit(
                current_session_identity=self._current_session()
            )
            self._candidate.commit(grant, current_session_identity=self._current_session())
        except (MycadError, ValueError) as exc:
            self.confirm_button.setEnabled(False)
            self.status_label.setText(f"确认失败：{exc}")
            return
        self._finished = True
        self.accept()

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            watched is self._viewport
            and not self._closed
            and self._current_session() == self._session_identity
            and not self._can_execute()
        ):
            if event.type() == QEvent.Type.KeyPress:
                self.status_label.setText("应用忙碌，请等待当前操作完成后再编辑草图。")
                return True
            if event.type() == QEvent.Type.MouseMove:
                mouse = cast("QMouseEvent", event)
                return not bool(mouse.buttons() & Qt.MouseButton.MiddleButton)
            if event.type() in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
            ):
                mouse = cast("QMouseEvent", event)
                if mouse.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                    if (
                        event.type() == QEvent.Type.MouseButtonRelease
                        and self._drag_start is not None
                    ):
                        self._drag_start = None
                        self._drag_reference = None
                        self._display_sketch(self.session.sketch)
                    self.status_label.setText("应用忙碌，请等待当前操作完成后再编辑草图。")
                    return True
        if (
            watched is self._viewport
            and not self._locked
            and self._is_current()
            and event.type() == QEvent.Type.KeyPress
            and cast("QKeyEvent", event).key() == Qt.Key.Key_Escape
        ):
            self.select_tool("select")
            return True
        if watched is self._viewport and self._locked and self._is_current():
            if self._region_mode:
                if (
                    event.type() == QEvent.Type.KeyPress
                    and cast("QKeyEvent", event).key() == Qt.Key.Key_Escape
                ):
                    self._clear_temporary_state()
                    self.status_label.setText("区域选择已取消。")
                    return True
                if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
                    mouse = cast("QMouseEvent", event)
                    identity = self._viewport.draft_sketch_region_at(
                        mouse.position().x(), mouse.position().y()
                    )
                    if event.type() == QEvent.Type.MouseButtonPress:
                        if mouse.button() != Qt.MouseButton.LeftButton:
                            return False
                        self.selected_region_ids = identity
                        self.status_label.setText(
                            "已选择区域；预览并完成草图后可用于建模。"
                            if identity
                            else "当前位置没有可选择的区域。"
                        )
                    else:
                        if identity == self._hovered_region:
                            return True
                        self._hovered_region = identity
                    self._viewport.set_draft_sketch_regions(
                        self._region_candidates,
                        selected=self.selected_region_ids,
                        hovered=self._hovered_region,
                    )
                    return True
            if self._dimension_kind is not None:
                if event.type() == QEvent.Type.KeyPress:
                    key = cast("QKeyEvent", event)
                    if key.key() == Qt.Key.Key_Escape:
                        self._clear_temporary_state()
                        self._display_sketch(self.session.sketch)
                        self.status_label.setText("画布标注已取消。")
                        return True
                if event.type() == QEvent.Type.MouseButtonPress:
                    mouse = cast("QMouseEvent", event)
                    if mouse.button() == Qt.MouseButton.LeftButton:
                        self._place_dimension_click(
                            mouse.position().x(),
                            mouse.position().y(),
                            bypass=bool(mouse.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                        )
                        return True
            if event.type() == QEvent.Type.MouseButtonDblClick and self._tool == "select":
                mouse = cast("QMouseEvent", event)
                if mouse.button() == Qt.MouseButton.LeftButton:
                    relations = self._viewport.draft_relations_at(
                        mouse.position().x(), mouse.position().y()
                    )
                    if self.selected_relation_id in relations:
                        return True
                    dimensions = self._viewport.draft_dimensions_at(
                        mouse.position().x(), mouse.position().y()
                    )
                    if dimensions:
                        identity = (
                            self.selected_dimension_id
                            if self.selected_dimension_id in dimensions
                            else dimensions[0]
                        )
                        assert identity is not None
                        self._edit_dimension_at(identity, mouse.position().toPoint())
                        return True
            if event.type() == QEvent.Type.KeyPress:
                key = cast("QKeyEvent", event)
                if self._tool == "spline" and key.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.finish_spline()
                    return True
                if key.key() == Qt.Key.Key_Escape:
                    self._clear_temporary_state()
                    self._tool = "select"
                    self.dynamic_input.configure("select")
                    self.offset_controls.hide()
                    self.mirror_keep_source.hide()
                    for name, button in self._tool_buttons.items():
                        button.setChecked(name == "select")
                    self._display_sketch(self.session.sketch)
                    return True
                if key.key() == Qt.Key.Key_Delete:
                    self.delete_selection()
                    return True
            if event.type() == QEvent.Type.MouseButtonPress and self._tool == "select":
                mouse = cast("QMouseEvent", event)
                if mouse.button() == Qt.MouseButton.LeftButton:
                    dimensions = self._viewport.draft_dimensions_at(
                        mouse.position().x(), mouse.position().y()
                    )
                    relations = self._viewport.draft_relations_at(
                        mouse.position().x(), mouse.position().y()
                    )
                    candidates = [("dimension", identity) for identity in dimensions] + [
                        ("relation", identity) for identity in relations
                    ]
                    if candidates:
                        point = (mouse.position().x(), mouse.position().y())
                        selected = (
                            ("dimension", self.selected_dimension_id)
                            if self.selected_dimension_id is not None
                            else ("relation", self.selected_relation_id or "")
                        )
                        cycle = (
                            self._selection_point is not None
                            and dist(self._selection_point, point) <= 4
                            and selected in candidates
                        )
                        index = (candidates.index(selected) + 1) % len(candidates) if cycle else 0
                        kind, identity = candidates[index]
                        self.selected_dimension_id = identity if kind == "dimension" else None
                        self.selected_relation_id = identity if kind == "relation" else None
                        self.selected_entity_id = None
                        self._drag_start = None
                        self._drag_reference = None
                        self._selection_point = point
                        self._display_sketch(self.session.sketch)
                        action = "双击修改驱动尺寸" if kind == "dimension" else "按 Delete 删除关系"
                        prefix = (
                            f"标注 {index + 1}/{len(candidates)}；再次单击切换，"
                            if len(candidates) > 1
                            else "已选择标注；"
                        )
                        self.status_label.setText(f"{prefix}{action}。")
                        return True
                    self._select_at(mouse.position().x(), mouse.position().y())
                    self._begin_drag(mouse.position().x(), mouse.position().y())
                    return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._tool == "select":
                mouse = cast("QMouseEvent", event)
                if mouse.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
                    self._finish_drag(
                        mouse.position().x(),
                        mouse.position().y(),
                        bypass=bool(mouse.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                    )
                    return True
            if (
                event.type() == QEvent.Type.MouseMove
                and self._tool == "select"
                and self._drag_reference is not None
                and self._drag_start is not None
            ):
                mouse = cast("QMouseEvent", event)
                preview = self._drag_result(
                    mouse.position().x(),
                    mouse.position().y(),
                    bypass=bool(mouse.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
                self._display_sketch(preview or self.session.sketch)
                return True
            if event.type() == QEvent.Type.MouseButtonPress and self._tool != "select":
                mouse = cast("QMouseEvent", event)
                if mouse.button() == Qt.MouseButton.RightButton:
                    if self._tool == "spline" and self._points:
                        self.finish_spline()
                    else:
                        self.select_tool("select")
                    return True
                if mouse.button() == Qt.MouseButton.LeftButton:
                    if self._tool == "mirror":
                        screen = (mouse.position().x(), mouse.position().y())
                        try:
                            if self._mirror_target_id is None:
                                self._mirror_target_id = self._visible_entity_at(*screen)
                                self._mirror_generation = self.session.generation
                                self.selected_entity_id = self._mirror_target_id
                                self._display_sketch(self.session.sketch)
                                self.status_label.setText("选择镜像轴的起点。")
                            elif self._mirror_axis_start is None:
                                self._mirror_axis_start = self._pointer_uv(*screen, bypass=True)
                                if self._mirror_axis_start is None:
                                    raise ValueError("视线与平面平行，请正视工作平面。")
                                self.status_label.setText("选择镜像轴的终点。")
                            else:
                                cached = self._trim_preview
                                candidate = (
                                    cached[2]
                                    if cached is not None
                                    and cached[0] == self.session.generation
                                    and dist(cached[1], screen) <= 1
                                    else self._mirror_candidate(*screen)
                                )
                                self._commit_mirror(candidate)
                        except ValueError as exc:
                            self.status_label.setText(str(exc))
                        return True
                    if self._tool in ("trim", "extend", "offset"):
                        try:
                            point = (mouse.position().x(), mouse.position().y())
                            cached = self._trim_preview
                            changed = (
                                cached[2]
                                if cached is not None
                                and cached[0] == self.session.generation
                                and dist(cached[1], point) <= 1
                                else self._curve_edit_candidate(*point)
                            )
                        except ValueError as exc:
                            self._display_sketch(self.session.sketch)
                            self.status_label.setText(str(exc))
                            return True
                        self.session.replace_sketch(changed)
                        self._trim_preview = None
                        self._invalidate_preview()
                        self.status_label.setText("修改已加入草稿；可继续操作或撤销。")
                        return True
                    bypass = bool(mouse.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                    uv = self._pointer_uv(
                        mouse.position().x(),
                        mouse.position().y(),
                        bypass=bypass,
                    )
                    if uv is None:
                        self.status_label.setText("视线与平面平行，请正视工作平面。")
                    else:
                        self.place_uv(uv, numeric=False, infer=not bypass)
                    return True
            if event.type() == QEvent.Type.MouseMove and self._tool != "select":
                mouse = cast("QMouseEvent", event)
                if self._tool == "mirror":
                    if self._mirror_target_id is not None and self._mirror_axis_start is not None:
                        screen = (mouse.position().x(), mouse.position().y())
                        try:
                            preview = self._mirror_candidate(*screen)
                            self._trim_preview = (self.session.generation, screen, preview)
                            end = self._pointer_uv(*screen, bypass=True)
                            if end is not None:
                                self._rubber_band_curve = tuple(
                                    self.session.sketch.frame.local_to_world(point)
                                    for point in (self._mirror_axis_start, end)
                                )
                        except ValueError:
                            self._trim_preview = None
                            self._rubber_band_curve = ()
                            preview = self.session.sketch
                        self._display_sketch(preview)
                    return True
                if self._tool in ("trim", "extend", "offset"):
                    try:
                        point = (mouse.position().x(), mouse.position().y())
                        preview = self._curve_edit_candidate(*point)
                        self._trim_preview = (self.session.generation, point, preview)
                    except ValueError:
                        self._trim_preview = None
                        preview = self.session.sketch
                    self._display_sketch(preview)
                    return True
                uv = self._pointer_uv(
                    mouse.position().x(),
                    mouse.position().y(),
                    bypass=bool(mouse.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
                if uv is not None and self._points:
                    self._preview_drawing(
                        uv, infer=not bool(mouse.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                    )
                elif uv is None:
                    self._rubber_band_curve = ()
                    self._display_sketch(self.session.sketch)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._tool != "select":
                return cast("QMouseEvent", event).button() == Qt.MouseButton.LeftButton
        return super().eventFilter(watched, event)

    @override
    def accept(self) -> None:
        if not self._closed:
            super().accept()

    @override
    def reject(self) -> None:
        if not self._closed:
            super().reject()

    def _cleanup(self, _result: int) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_dimension_editor()
        if self.constraint_dialog is not None:
            self.constraint_dialog.reject()
        self._viewport.removeEventFilter(self)
        self._viewport.datum_selection_changed.disconnect(self._on_datum_selected)
        self._viewport.selection_changed.disconnect(self._on_face_selected)
        if not self._finished:
            self._candidate.cancel()
        if self._current_session() == self._session_identity:
            self._viewport.set_selection_filter(self._saved_selection_filter)
            self._viewport.set_draft_sketch_curves(())
            self._viewport.set_draft_sketch_points(())
            self._viewport.set_draft_sketch_control_points(())
            self._viewport.set_draft_relation_labels(())
            self._viewport.set_draft_sketch_dimensions(())
            self._viewport.set_draft_sketch_regions(())
            self._viewport.set_active_draft_sketch(None)
            self._viewport.set_workplane_grid(None, self.grid_spacing.value())
            self._viewport.set_position_markers(None)
            self._viewport.clear_candidate_preview()
            self._viewport.refresh()
            self._viewport.restore_view(self._saved_view)
