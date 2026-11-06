# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicit, isolated datum-creation task for the part workspace."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, cast, override

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mycad import app
from mycad.core.exceptions import MycadError
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import Point3D, WorkPlaneFrame
from mycad.core.spatial_frames import RigidFrame
from mycad.core.spatial_references import SpatialReference
from mycad.core.viewport_protocol import CandidateInteractionScene
from mycad.ui.workplane_position import WorkplanePositionDialog

if TYPE_CHECKING:
    from mycad.core.persistence import LoadedDocument
    from mycad.ui.viewport import GLViewport


def _rotation_axes(x: float, y: float, z: float) -> tuple[tuple[float, ...], ...]:
    rx, ry, rz = map(math.radians, (x, y, z))
    sx, cx = math.sin(rx), math.cos(rx)
    sy, cy = math.sin(ry), math.cos(ry)
    sz, cz = math.sin(rz), math.cos(rz)
    return (
        (cz * cy, sz * cy, -sy),
        (cz * sy * sx - sz * cx, sz * sy * sx + cz * cx, cy * sx),
        (cz * sy * cx + sz * sx, sz * sy * cx - cz * sx, cy * cx),
    )


class DatumTaskDialog(QDialog):
    """Stage and preview a single coordinate system or datum-plane command."""

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
        embedded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("创建基准")
        self._services = services
        self._loaded = loaded
        self._viewport = viewport
        self._session_identity = session_identity
        self._source_revision = loaded.document.revision
        self._source_expired = False
        self._current_session = current_session or (lambda: session_identity)
        self._can_execute = can_execute or (lambda: True)
        self._candidate = app.create_replay_candidate(
            services, loaded, session_identity=session_identity
        )
        self._finished = False
        self._viewport_disconnected = False
        self._draft_revision = 0
        self._adopting_position = False
        self._adopted_origin: Point3D | None = None
        self._hotspot: Point3D | None = None
        self._hotspot_scene: CandidateInteractionScene | None = None
        self._picking_origin = False
        self._hotspot_pressed = False
        self._hotspot_press_pos: tuple[float, float] | None = None
        self._snap_point: Point3D | None = None
        self.position_dialog: WorkplanePositionDialog | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)
        self._preview_timer.timeout.connect(self.preview)

        self.kind_combo = QComboBox(self)
        self.kind_combo.addItems(("相对坐标系", "主基准面", "偏置基准面"))
        self.name_field = QLineEdit("坐标系", self)
        self.parent_combo = QComboBox(self)
        self.plane_combo = QComboBox(self)
        self.plane_combo.addItems(("XY", "XZ", "YZ"))
        self.offset_field = self._number()
        self.origin_fields = tuple(self._number() for _ in range(3))
        self.angle_fields = tuple(self._number() for _ in range(3))
        self.status_label = QLabel("输入参数后预览，确认后提交。", self)
        self.status_label.setWordWrap(True)
        self.preview_button = QPushButton("预览", self)
        self.position_button = QPushButton("在平面上定位原点", self)
        self.point_button = QPushButton("捕捉三维特征点", self)
        self.confirm_button = QPushButton("确认", self)
        self.confirm_button.setEnabled(False)
        self.cancel_button = QPushButton("取消", self)
        fields = (
            ("类型", self.kind_combo),
            ("名称", self.name_field),
            ("父基准", self.parent_combo),
            ("主平面", self.plane_combo),
            ("偏置 mm", self.offset_field),
            *zip(("父系 X mm", "父系 Y mm", "父系 Z mm"), self.origin_fields, strict=True),
            *zip(("绕父 X °", "绕父 Y °", "绕父 Z °"), self.angle_fields, strict=True),
        )
        if embedded:
            layout = QHBoxLayout(self)
            layout.setContentsMargins(6, 2, 6, 2)
            self.status_label.setFixedWidth(200)
            layout.addWidget(self.status_label)
            for label, field in fields:
                layout.addWidget(QLabel(label, self))
                field.setMinimumWidth(90)
                layout.addWidget(field)
            for button in (self.position_button, self.point_button, self.preview_button):
                layout.addWidget(button)
        else:
            form = QFormLayout()
            for label, field in fields:
                form.addRow(label, field)
            form.addRow(self.position_button)
            form.addRow(self.point_button)
            buttons = QHBoxLayout()
            for button in (self.preview_button, self.confirm_button, self.cancel_button):
                buttons.addWidget(button)
            vertical = QVBoxLayout(self)
            vertical.addLayout(form)
            vertical.addWidget(self.status_label)
            vertical.addLayout(buttons)
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        self.parent_combo.currentIndexChanged.connect(self._invalidate)
        self.parent_combo.currentIndexChanged.connect(self._clear_adopted_origin)
        self.plane_combo.currentIndexChanged.connect(self._invalidate)
        self.name_field.textChanged.connect(self._invalidate)
        for field in (*self.origin_fields, *self.angle_fields, self.offset_field):
            field.valueChanged.connect(self._invalidate)
            field.lineEdit().textEdited.connect(self._invalidate)
        for field in self.origin_fields:
            field.valueChanged.connect(self._clear_adopted_origin)
            field.lineEdit().textEdited.connect(self._clear_adopted_origin)
        self.preview_button.clicked.connect(self.preview)
        self.position_button.clicked.connect(self.open_positioning)
        self.point_button.clicked.connect(self.start_origin_pick)
        self.confirm_button.clicked.connect(self.confirm)
        self.cancel_button.clicked.connect(self.reject)
        self._viewport.datum_selection_changed.connect(self._on_datum_selected)
        self._viewport.installEventFilter(self)
        self.finished.connect(self._disconnect_viewport)
        self._source_changed.connect(self._expire_if_source_changed)
        for event in (
            "post_command",
            "command_amended",
            "geometry_rebuilt",
            "metadata_changed",
            "named_group_added",
            "named_group_removed",
        ):
            loaded.document.events.subscribe(event, self._on_document_event)
        self._kind_changed()

    def _on_document_event(self, _payload: Mapping[str, object]) -> None:
        if not self._finished:
            self._source_changed.emit()

    def _expire_if_source_changed(self) -> None:
        if self._finished or self._loaded.document.revision == self._source_revision:
            return
        self._source_expired = True
        self._preview_timer.stop()
        self.confirm_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.position_button.setEnabled(False)
        self.point_button.setEnabled(False)
        self._stop_origin_pick()
        if self.position_dialog is not None:
            self.position_dialog.reject()
        if self._current_session() == self._session_identity:
            self._viewport.clear_candidate_preview()
        self.status_label.setText("模型已改变，请退出并重新创建基准。")

    def _disconnect_viewport(self, _result: int) -> None:
        if self._viewport_disconnected:
            return
        self._viewport_disconnected = True
        self._stop_origin_pick()
        self._viewport.removeEventFilter(self)
        self._viewport.datum_selection_changed.disconnect(self._on_datum_selected)
        if self._current_session() == self._session_identity:
            self._viewport.set_datum_pick_filter(None)

    def _on_datum_selected(self, reference: object) -> None:
        if (
            self._finished
            or self._current_session() != self._session_identity
            or self.position_dialog is not None
            or not isinstance(reference, SpatialReference)
        ):
            return
        for index in range(self.parent_combo.count()):
            if self.parent_combo.itemData(index) == reference:
                self.parent_combo.setCurrentIndex(index)
                return

    def _number(self) -> QDoubleSpinBox:
        field = QDoubleSpinBox(self)
        field.setDecimals(6)
        field.setRange(-1_000_000, 1_000_000)
        return field

    def _clear_adopted_origin(self) -> None:
        self._adopted_origin = None

    def _kind_changed(self) -> None:
        if self._finished or self._current_session() != self._session_identity:
            return
        index = self.kind_combo.currentIndex()
        previous = self.parent_combo.blockSignals(True)
        self.parent_combo.clear()
        if index != 2:
            self.parent_combo.addItem("世界坐标系", SpatialReference("world"))
        expected = "datum_plane" if index == 2 else "coordinate_system"
        for datum in self._services.kernel.datum_display_data():
            if datum.reference.kind == expected:
                self.parent_combo.addItem(
                    f"{datum.name} · {(datum.reference.source_instance_id or '')[:8]}",
                    datum.reference,
                )
        self.parent_combo.blockSignals(previous)
        references: set[SpatialReference] = set()
        for position in range(self.parent_combo.count()):
            reference = self.parent_combo.itemData(position)
            if isinstance(reference, SpatialReference):
                references.add(reference)
        self._viewport.set_datum_pick_filter(frozenset(references))
        self.plane_combo.setEnabled(index == 1)
        self.offset_field.setEnabled(index == 2)
        self.position_button.setEnabled(index == 0 and not self._source_expired)
        self.point_button.setEnabled(index == 0 and not self._source_expired)
        for field in (*self.origin_fields, *self.angle_fields):
            field.setEnabled(index == 0)
        self._invalidate()

    def _invalidate(self) -> None:
        if (
            self._finished
            or self._source_expired
            or self._current_session() != self._session_identity
        ):
            return
        self._draft_revision += 1
        self._stop_origin_pick()
        if self.position_dialog is not None and not self._adopting_position:
            self.position_dialog.reject()
        self.confirm_button.setEnabled(False)
        self._viewport.clear_candidate_preview()
        self._preview_timer.start()

    def _parameters(self) -> tuple[str, dict[str, object]]:
        for field in (*self.origin_fields, *self.angle_fields, self.offset_field):
            if field.isEnabled():
                if not field.hasAcceptableInput():
                    raise ValueError("请输入有效的数值。")
                field.interpretText()
        parent = self.parent_combo.currentData()
        if not isinstance(parent, SpatialReference):
            raise ValueError("请选择有效的父基准。")
        name = self.name_field.text().strip()
        if not name:
            raise ValueError("请输入基准名称。")
        index = self.kind_combo.currentIndex()
        if index == 0:
            axes = _rotation_axes(*(field.value() for field in self.angle_fields))
            return "datum.coordinate_system.create", {
                "name": name,
                "parent": parent.to_mapping(),
                "origin_mm": list(self._adopted_origin)
                if self._adopted_origin is not None
                else [field.value() for field in self.origin_fields],
                "x_axis": list(axes[0]),
                "y_axis": list(axes[1]),
                "z_axis": list(axes[2]),
            }
        if index == 1:
            construction: dict[str, object] = {
                "kind": "principal",
                "coordinate_system": parent.to_mapping(),
                "plane": self.plane_combo.currentText().lower(),
            }
        else:
            construction = {
                "kind": "offset",
                "plane": parent.to_mapping(),
                "distance_mm": self.offset_field.value(),
            }
        return "datum.plane.create", {"name": name, "construction": construction}

    def preview(self) -> None:
        self._preview_timer.stop()
        if self._finished or self._current_session() != self._session_identity:
            return
        self._stop_origin_pick()
        self.confirm_button.setEnabled(False)
        if self._source_expired:
            return
        if not self._can_execute():
            self.status_label.setText("几何工作线程忙碌，请稍后重新预览。")
            return
        try:
            command_id, params = self._parameters()
            change = ReplayChangeSet((), (ReplayAppend(command_id, 1, params, "local"),), False, 6)
            self._candidate.stage(change, current_session_identity=self._current_session())
            result = self._candidate.preview(current_session_identity=self._current_session())
            if result.scene is None:
                raise ValueError(f"预览失败：{result.failure or result.state}")
            scene = result.scene
            self._viewport.show_interaction_scene(
                scene,
                session_identity=self._current_session(),
                is_current=lambda: self._candidate.is_scene_current(
                    scene, current_session_identity=self._current_session()
                ),
            )
            self._hotspot_scene = scene
            self._hotspot = (
                scene.datums[-1].frame.origin_mm
                if command_id == "datum.coordinate_system.create" and scene.datums
                else None
            )
            self._viewport.set_origin_hotspot(self._hotspot)
            action = "升级到 v6 并提交" if self._loaded.document.archive_version < 6 else "提交"
            self.status_label.setText(f"预览成功：{params['name']}；确认后{action}。")
            self.confirm_button.setEnabled(True)
        except (MycadError, ValueError) as exc:
            self._viewport.clear_candidate_preview()
            self.status_label.setText(f"预览不可用：{exc}")

    def _stop_origin_pick(self) -> None:
        self._picking_origin = False
        self._hotspot_pressed = False
        self._hotspot_press_pos = None
        self._snap_point = None
        self._hotspot = None
        self._hotspot_scene = None
        if self._current_session() == self._session_identity:
            self._viewport.set_origin_hotspot(None)
            self._viewport.set_position_markers(None)

    def start_origin_pick(self) -> None:
        if (
            self._finished
            or self.kind_combo.currentIndex() != 0
            or self._source_expired
            or self.position_dialog
        ):
            return
        if self._hotspot is None:
            self.preview()
        if not self._origin_scene_current():
            return
        self._picking_origin = True
        self._snap_point = None
        self.confirm_button.setEnabled(False)
        self.status_label.setText("移动到实体端点、中点或圆心，点击采用；Esc 取消取点。")

    def _origin_scene_current(self) -> bool:
        scene = self._hotspot_scene
        return bool(
            self._hotspot is not None
            and scene is not None
            and self._can_execute()
            and self._candidate.is_scene_current(
                scene, current_session_identity=self._current_session()
            )
        )

    def _pick_origin_at(self, x: float, y: float) -> None:
        if not self._origin_scene_current() or not self._viewport.interaction_datums():
            self._snap_point = None
            self._viewport.set_position_markers(None)
            return
        options: list[tuple[float, int, str, Point3D, str]] = []
        priority = {"vertex": 0, "center": 1, "midpoint": 2}
        for anchor in self._viewport.interaction_snap_anchors():
            screen = self._viewport.project_world_point(anchor.point)
            if screen is None:
                continue
            distance = math.dist((x, y), screen)
            if distance <= 12:
                key = anchor.source_key or str(
                    anchor.topology_id.value if anchor.topology_id else ""
                )
                options.append((distance, priority[anchor.kind], key, anchor.point, anchor.kind))
        origins = [("world", (0.0, 0.0, 0.0))] if self._viewport.coordinate_axes_visible() else []
        scene = self._hotspot_scene
        created_id = (
            self._candidate.proposal.commands[-1].instance_id if self._candidate.proposal else None
        )
        if scene is not None:
            origins.extend(
                (datum.reference.source_instance_id or "world", datum.frame.origin_mm)
                for datum in self._viewport.interaction_datums()
                if datum.reference.source_instance_id != created_id
            )
        for key, point in origins:
            screen = self._viewport.project_world_point(point)
            if screen is not None:
                distance = math.dist((x, y), screen)
                if distance <= 12:
                    options.append((distance, 0, key, point, "origin"))
        if options:
            choice = min(options, key=lambda item: item[:3])
            self._snap_point = choice[3]
            self._viewport.set_position_markers(choice[3])
            label = {"vertex": "端点", "midpoint": "中点", "center": "圆心", "origin": "原点"}[
                choice[4]
            ]
            self.status_label.setText(f"捕捉{label} · 世界 XYZ {choice[3]}；点击采用。")
        else:
            self._snap_point = None
            self._viewport.set_position_markers(None)
            self.status_label.setText("未捕捉到特征点，请靠近实体端点、中点或圆心。")

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            watched is not self._viewport
            or self.position_dialog is not None
            or self._finished
            or self._current_session() != self._session_identity
        ):
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.KeyPress and self._picking_origin:
            from PySide6.QtGui import QKeyEvent

            if cast("QKeyEvent", event).key() == Qt.Key.Key_Escape:
                self._stop_origin_pick()
                self.preview()
                return True
        if event.type() == QEvent.Type.MouseMove and self._picking_origin:
            mouse = cast("QMouseEvent", event)
            if mouse.buttons() in (Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton):
                self._pick_origin_at(mouse.position().x(), mouse.position().y())
                return True
        if event.type() == QEvent.Type.MouseButtonPress:
            mouse = cast("QMouseEvent", event)
            if mouse.button() == Qt.MouseButton.LeftButton:
                x, y = mouse.position().x(), mouse.position().y()
                if self._picking_origin:
                    self._pick_origin_at(x, y)
                    if self._snap_point is not None:
                        self._adopt_world_origin(self._snap_point)
                    return True
                screen = (
                    self._viewport.project_world_point(self._hotspot) if self._hotspot else None
                )
                if screen is not None and math.dist((x, y), screen) <= 12:
                    self.start_origin_pick()
                    self._hotspot_pressed = True
                    self._hotspot_press_pos = (x, y)
                    return True
        if event.type() == QEvent.Type.MouseButtonRelease and self._hotspot_pressed:
            self._hotspot_pressed = False
            mouse = cast("QMouseEvent", event)
            position = (mouse.position().x(), mouse.position().y())
            if (
                self._hotspot_press_pos is not None
                and math.dist(position, self._hotspot_press_pos) > 3
            ):
                self._pick_origin_at(*position)
                if self._snap_point is not None:
                    self._adopt_world_origin(self._snap_point)
            self._hotspot_press_pos = None
            return True
        return super().eventFilter(watched, event)

    def confirm(self) -> None:
        if self._finished or not self.confirm_button.isEnabled():
            return
        if not self._can_execute():
            self.confirm_button.setEnabled(False)
            self.status_label.setText("几何工作线程忙碌，请稍后重新预览。")
            return
        try:
            command_id, params = self._parameters()
            proposal = self._candidate.proposal
            if (
                proposal is None
                or not proposal.commands
                or proposal.commands[-1].id != command_id
                or proposal.commands[-1].params != params
            ):
                raise ValueError("参数已变化，请重新预览。")
            current = self._current_session()
            grant = self._candidate.authorize_commit(current_session_identity=current)
            self._candidate.commit(grant, current_session_identity=current)
        except (MycadError, ValueError) as exc:
            self.confirm_button.setEnabled(False)
            self.status_label.setText(f"无法确认：{exc}")
            return
        self._finished = True
        self._viewport.clear_candidate_preview()
        self._viewport.refresh()
        self.accept()

    def open_positioning(self) -> None:
        if (
            self._finished
            or self._current_session() != self._session_identity
            or self.kind_combo.currentIndex() != 0
        ):
            return
        self.preview()
        if not self.confirm_button.isEnabled() or self._candidate.proposal is None:
            return
        proposal = self._candidate.proposal
        draft_revision = self._draft_revision
        planes: list[tuple[str, WorkPlaneFrame, SpatialReference | None]] = [
            (f"世界 {name.upper()}", RigidFrame.identity().principal_plane(name), None)
            for name in ("xy", "xz", "yz")
        ]
        for datum in self._services.kernel.datum_display_data():
            if isinstance(datum.frame, WorkPlaneFrame):
                planes.append((datum.name, datum.frame, datum.reference))
        if self.position_dialog is not None:
            self.position_dialog.reject()
        dialog = WorkplanePositionDialog(
            planes,
            self._viewport,
            self._adopt_world_origin,
            lambda: (
                self._candidate.proposal is proposal
                and self._candidate.state == "succeeded"
                and self._can_execute()
                and self._draft_revision == draft_revision
                and self._current_session() == self._session_identity
                and self._loaded.document.revision == proposal.revision
            ),
            self,
            owns_viewport=lambda: self._current_session() == self._session_identity,
        )
        self.position_dialog = dialog
        self.confirm_button.setEnabled(False)

        def finished(_result: int) -> None:
            if self.position_dialog is dialog:
                self.position_dialog = None
            if (
                self._draft_revision == draft_revision
                and self._candidate.proposal is proposal
                and self._candidate.state == "succeeded"
                and self._loaded.document.revision == proposal.revision
                and self._current_session() == self._session_identity
            ):
                self.confirm_button.setEnabled(True)

        dialog.finished.connect(finished)
        dialog.show()

    def _adopt_world_origin(self, point: Point3D) -> None:
        reference = self.parent_combo.currentData()
        frame = RigidFrame.identity()
        if isinstance(reference, SpatialReference) and reference.kind == "coordinate_system":
            match = next(
                (
                    datum
                    for datum in self._services.kernel.datum_display_data()
                    if datum.reference == reference
                ),
                None,
            )
            if match is None or not isinstance(match.frame, RigidFrame):
                raise ValueError("父坐标系已失效。")
            frame = match.frame
        local = frame.world_to_local(point)
        blockers = [QSignalBlocker(field) for field in self.origin_fields]
        for field, value in zip(self.origin_fields, local, strict=True):
            field.setValue(value)
        del blockers
        self._adopting_position = True
        try:
            self._invalidate()
        finally:
            self._adopting_position = False
        self._adopted_origin = local

    @override
    def accept(self) -> None:
        if not self._viewport_disconnected:
            super().accept()

    @override
    def reject(self) -> None:
        if self._finished:
            return
        self._preview_timer.stop()
        if self.position_dialog is not None:
            self.position_dialog.reject()
        self._candidate.cancel()
        if self._current_session() == self._session_identity:
            self._viewport.clear_candidate_preview()
        self._finished = True
        super().reject()
