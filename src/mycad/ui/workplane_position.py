# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A locked workplane for positioning a datum origin."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, cast, override

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mycad.core.sketch import Point3D, WorkPlaneFrame
from mycad.core.spatial_positioning import (
    ObjectSnap,
    ProjectedAnchor,
    intersect_plane,
    locate_uv,
    object_snap_candidates,
)
from mycad.core.spatial_references import SpatialReference

if TYPE_CHECKING:
    from mycad.ui.viewport import GLViewport


class WorkplanePositionDialog(QDialog):
    """Choose a workplane and explicitly adopt a UV point into a draft."""

    def __init__(
        self,
        planes: Sequence[tuple[str, WorkPlaneFrame, SpatialReference | None]],
        viewport: GLViewport,
        adopt_point: Callable[[Point3D], None],
        is_current: Callable[[], bool],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("在平面上定位原点")
        self._adopt_point = adopt_point
        self._viewport = viewport
        self._is_current = is_current
        self._locked_plane: WorkPlaneFrame | None = None
        self._numeric_locked = False
        self._pointer_world: Point3D | None = None
        self._previous_filter = viewport.datum_pick_filter()
        self._plane_indices: dict[SpatialReference, int] = {}
        self.plane_combo = QComboBox(self)
        for index, (label, frame, reference) in enumerate(planes):
            self.plane_combo.addItem(label, frame)
            if reference is not None:
                self._plane_indices[reference] = index
        self._viewport.set_datum_pick_filter(frozenset(self._plane_indices))
        self._viewport.datum_selection_changed.connect(self._select_plane)
        self.lock_button = QPushButton("锁定平面", self)
        self.u_field = self._number()
        self.v_field = self._number()
        self.object_snap = QCheckBox("对象捕捉", self)
        self.object_snap.setChecked(True)
        self.grid_visible = QCheckBox("显示栅格", self)
        self.grid_snap = QCheckBox("栅格吸附", self)
        self.project_snap = QCheckBox("一次投影离面捕捉点", self)
        self.snap_choices = QComboBox(self)
        self.snap_choices.setEnabled(False)
        self.grid_spacing = self._number()
        self.grid_spacing.setRange(0.000001, 1_000_000)
        self.grid_spacing.setValue(10)
        self.status_label = QLabel("选择工作平面后锁定。", self)
        self.grid_status = QLabel("栅格吸附：关闭", self)
        self.adopt_button = QPushButton("采用位置", self)
        self.repick_button = QPushButton("重新拾点", self)
        self.look_button = QPushButton("正视工作平面", self)
        self.adopt_button.setEnabled(False)
        cancel_button = QPushButton("取消", self)
        form = QFormLayout()
        form.addRow("工作平面", self.plane_combo)
        form.addRow(self.lock_button)
        form.addRow("U mm", self.u_field)
        form.addRow("V mm", self.v_field)
        form.addRow(self.object_snap)
        form.addRow(self.grid_visible)
        form.addRow(self.grid_snap)
        form.addRow(self.project_snap)
        form.addRow("重叠捕捉点", self.snap_choices)
        form.addRow("栅格间距 mm", self.grid_spacing)
        form.addRow(self.look_button)
        form.addRow(self.repick_button)
        buttons = QHBoxLayout()
        buttons.addWidget(self.adopt_button)
        buttons.addWidget(cancel_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addWidget(self.grid_status)
        layout.addLayout(buttons)
        self.lock_button.clicked.connect(self._toggle_lock)
        self.plane_combo.currentIndexChanged.connect(self._unlock)
        self.u_field.valueChanged.connect(self._numeric_changed)
        self.v_field.valueChanged.connect(self._numeric_changed)
        for field in (self.u_field, self.v_field):
            field.lineEdit().textEdited.connect(self._numeric_changed)
        self.grid_visible.toggled.connect(self._update_grid)
        self.grid_visible.toggled.connect(self._update_grid_status)
        self.grid_snap.toggled.connect(self._update_grid_status)
        self.grid_spacing.valueChanged.connect(self._update_grid)
        self.look_button.clicked.connect(self._look_at)
        self.repick_button.clicked.connect(self._repick)
        self.snap_choices.activated.connect(self._choose_snap)
        self.adopt_button.clicked.connect(self.adopt)
        cancel_button.clicked.connect(self.reject)
        self._viewport.installEventFilter(self)
        self.finished.connect(self._cleanup)

    def _number(self) -> QDoubleSpinBox:
        field = QDoubleSpinBox(self)
        field.setDecimals(6)
        field.setRange(-1_000_000, 1_000_000)
        return field

    def _unlock(self) -> None:
        self._locked_plane = None
        self._pointer_world = None
        self.plane_combo.setEnabled(True)
        self.lock_button.setText("锁定平面")
        self._viewport.set_workplane_grid(None, self.grid_spacing.value())
        self.adopt_button.setEnabled(False)
        self.status_label.setText("选择工作平面后锁定。")

    def lock_plane(self) -> None:
        plane = self.plane_combo.currentData()
        if not isinstance(plane, WorkPlaneFrame) or not self._is_current():
            self._unlock()
            self.status_label.setText("工作平面或候选已失效。")
            return
        self._locked_plane = plane
        self.plane_combo.setEnabled(False)
        self.lock_button.setText("重新选择平面")
        self._numeric_locked = False
        self.adopt_button.setEnabled(True)
        self._update_status()
        self._update_grid()

    def _toggle_lock(self) -> None:
        if self._locked_plane is None:
            self.lock_plane()
        else:
            self._unlock()

    def _numeric_changed(self) -> None:
        if self._locked_plane is None:
            return
        self._numeric_locked = True
        self._pointer_world = None
        if not self.u_field.hasAcceptableInput() or not self.v_field.hasAcceptableInput():
            self.adopt_button.setEnabled(False)
            self._viewport.set_position_markers(None)
            self.status_label.setText("请输入有效的 U/V 数值。")
            return
        self.adopt_button.setEnabled(True)
        self._update_status()

    def _update_status(self) -> None:
        if self._locked_plane is None:
            return
        result = locate_uv(
            (self.u_field.value(), self.v_field.value()),
            self._locked_plane,
            numeric=True,
            grid_enabled=self.grid_snap.isChecked(),
            spacing=self.grid_spacing.value(),
        )
        self.status_label.setText(
            f"已锁定 {self.plane_combo.currentText()} · 世界 XYZ {result.world}"
        )
        if self._numeric_locked:
            self._viewport.set_position_markers(result.world)

    def _update_grid(self) -> None:
        frame = self._locked_plane if self.grid_visible.isChecked() else None
        self._viewport.set_workplane_grid(frame, self.grid_spacing.value())

    def _update_grid_status(self) -> None:
        if not self.grid_snap.isChecked():
            self.grid_status.setText("栅格吸附：关闭")
        elif self.grid_visible.isChecked():
            self.grid_status.setText("栅格吸附：开启")
        else:
            self.grid_status.setText("栅格吸附：开启（栅格隐藏）")

    def _look_at(self) -> None:
        if self._locked_plane is not None:
            self._viewport.look_at_workplane(self._locked_plane)

    def _repick(self) -> None:
        self._numeric_locked = False
        self._pointer_world = None
        self.status_label.setText("移动鼠标定位；单击锁定位置。")

    def _choose_snap(self, index: int) -> None:
        snap = self.snap_choices.itemData(index)
        if not isinstance(snap, ObjectSnap) or self._locked_plane is None or not self._is_current():
            return
        self._numeric_locked = True
        self._pointer_world = snap.world
        blockers = (QSignalBlocker(self.u_field), QSignalBlocker(self.v_field))
        self.u_field.setValue(snap.uv[0])
        self.v_field.setValue(snap.uv[1])
        del blockers
        self._viewport.set_position_markers(
            snap.world, snap.anchor.world if snap.projected else None
        )
        self.adopt_button.setEnabled(True)
        self.status_label.setText(
            f"{snap.anchor.kind} · {snap.anchor.key} · UV {snap.uv} · 世界 XYZ {snap.world}"
        )

    def _cleanup(self, _result: int) -> None:
        self._viewport.removeEventFilter(self)
        self._viewport.set_workplane_grid(None, self.grid_spacing.value())
        self._viewport.set_position_markers(None)
        self._viewport.datum_selection_changed.disconnect(self._select_plane)
        self._viewport.set_datum_pick_filter(self._previous_filter)

    def _select_plane(self, reference: object) -> None:
        if (
            self._locked_plane is None
            and isinstance(reference, SpatialReference)
            and reference in self._plane_indices
        ):
            self.plane_combo.setCurrentIndex(self._plane_indices[reference])

    def _pointer_position(self, event: QMouseEvent) -> None:
        plane = self._locked_plane
        if plane is None or self._numeric_locked or not self._is_current():
            return
        x, y = float(event.position().x()), float(event.position().y())
        ray = self._viewport.camera_ray(x, y)
        point = None if ray is None else intersect_plane(ray[0], ray[1], plane)
        if point is None:
            self._pointer_world = None
            self.adopt_button.setEnabled(False)
            self._viewport.set_position_markers(None)
            self.status_label.setText("视线与工作平面平行或背向，请正视工作平面。")
            return
        bypass = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        snapped = None
        options: tuple[ObjectSnap, ...] = ()
        if self.object_snap.isChecked() and not bypass:
            anchors: list[ProjectedAnchor] = []
            for item in self._viewport.interaction_snap_anchors():
                screen = self._viewport.project_world_point(item.point)
                if screen is not None:
                    key = item.source_key or str(item.topology_id.value if item.topology_id else "")
                    anchors.append(ProjectedAnchor(item.kind, key, item.point, screen))
            origins = (
                [("world", (0.0, 0.0, 0.0))] if self._viewport.coordinate_axes_visible() else []
            )
            origins.extend(
                (str(datum.reference.source_instance_id), datum.frame.origin_mm)
                for datum in self._viewport.interaction_datums()
            )
            for identity, origin in origins:
                screen = self._viewport.project_world_point(origin)
                if screen is not None:
                    anchors.append(ProjectedAnchor("origin", identity, origin, screen))
            options = object_snap_candidates(
                anchors, (x, y), plane, allow_projection=self.project_snap.isChecked()
            )
            snapped = options[0] if options else None
        blocker = QSignalBlocker(self.snap_choices)
        self.snap_choices.clear()
        for option in options:
            self.snap_choices.addItem(
                f"{option.anchor.kind} · {option.anchor.key} · {option.anchor.world}", option
            )
        self.snap_choices.setEnabled(len(options) > 1)
        del blocker
        if snapped is None:
            result = locate_uv(
                plane.world_to_local(point),
                plane,
                numeric=False,
                grid_enabled=self.grid_snap.isChecked() and not bypass,
                spacing=self.grid_spacing.value(),
            )
            uv, description = result.uv, result.source
            self._pointer_world = result.world
            self._viewport.set_position_markers(result.world)
        else:
            uv = snapped.uv
            self._pointer_world = snapped.world
            description = f"{snapped.anchor.kind}{'（一次投影）' if snapped.projected else ''}"
            self._viewport.set_position_markers(
                snapped.world, snapped.anchor.world if snapped.projected else None
            )
            if snapped.projected:
                description += f" 源 XYZ {snapped.anchor.world} → 投影 XYZ {snapped.world}"
        blockers = (QSignalBlocker(self.u_field), QSignalBlocker(self.v_field))
        self.u_field.setValue(uv[0])
        self.v_field.setValue(uv[1])
        del blockers
        self.adopt_button.setEnabled(True)
        self.status_label.setText(f"{self.plane_combo.currentText()} · {description} · UV {uv}")

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._viewport and self._locked_plane is not None:
            if event.type() == QEvent.Type.MouseMove:
                mouse = cast("QMouseEvent", event)
                if mouse.buttons() == Qt.MouseButton.NoButton:
                    self._pointer_position(mouse)
            elif event.type() == QEvent.Type.MouseButtonPress:
                mouse = cast("QMouseEvent", event)
                if mouse.button() == Qt.MouseButton.LeftButton:
                    self._pointer_position(mouse)
                    if self.adopt_button.isEnabled():
                        self._numeric_locked = True
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                mouse = cast("QMouseEvent", event)
                if mouse.button() == Qt.MouseButton.LeftButton:
                    return True
        return super().eventFilter(watched, event)

    def adopt(self) -> None:
        if self._locked_plane is None or not self._is_current():
            self._unlock()
            self.status_label.setText("候选已失效，请重新预览。")
            return
        if not self.u_field.hasAcceptableInput() or not self.v_field.hasAcceptableInput():
            self.adopt_button.setEnabled(False)
            self.status_label.setText("请输入有效的 U/V 数值。")
            return
        self.u_field.interpretText()
        self.v_field.interpretText()
        result = locate_uv(
            (self.u_field.value(), self.v_field.value()),
            self._locked_plane,
            numeric=True,
            grid_enabled=self.grid_snap.isChecked(),
            spacing=self.grid_spacing.value(),
        )
        self._adopt_point(self._pointer_world if self._pointer_world is not None else result.world)
        self.accept()
