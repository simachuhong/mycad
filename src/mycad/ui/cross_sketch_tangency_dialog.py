# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Choose two owned curves and explicitly preview a cross-sketch tangency."""

from __future__ import annotations

import math
from typing import cast
from uuid import uuid4

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    TangencyBranch,
    infer_tangency_branch,
    project_tangent_entity,
    resolve_tangent_curve,
)
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
)
from mycad.ui.workspace_console import drawing_message


def _describe_curve(reference: CrossSketchRef, sketches: tuple[Sketch, ...]) -> str:
    owner = next(sketch for sketch in sketches if sketch.sketch_id == reference.sketch_id)
    curve = resolve_tangent_curve(owner, reference)
    if isinstance(curve, LineEntity):
        return f"直线 ({curve.start_mm[0]:.3f}, {curve.start_mm[1]:.3f}) → ({curve.end_mm[0]:.3f}, {curve.end_mm[1]:.3f})"
    result = (
        f"圆心 ({curve.center_mm[0]:.3f}, {curve.center_mm[1]:.3f})，半径 {curve.radius_mm:.3f}"
    )
    if isinstance(curve, ArcEntity):
        result += f"，起角 {curve.start_angle_deg:.2f}°，扫角 {curve.sweep_angle_deg:.2f}°"
    return result


def tangent_preview_summary(
    relation: CrossSketchTangency, original: tuple[Sketch, ...], solved: tuple[Sketch, ...]
) -> str:
    """Show both source and solved finite curves in their own sketch coordinates."""
    lines = ["预览有效，确认后写入相切关系。坐标使用各对象的坐标系，长度单位为 mm。"]
    for index, reference in enumerate((relation.first, relation.second), 1):
        lines.append(f"曲线 {index}：{_describe_curve(reference, original)}")
        lines.append(f"求解后：{_describe_curve(reference, solved)}")
    return "\n".join(lines)


class CrossSketchTangencyDialog(QDialog):
    """Offer stable owned-curve references and a user-selected solution branch."""

    preview_requested = Signal(object)
    commit_requested = Signal(object)
    remove_requested = Signal(str)
    canvas_selection_requested = Signal()
    preview_completed = Signal(bool)

    def __init__(
        self,
        sketches: tuple[Sketch, ...],
        relations: tuple[CrossSketchTangency, ...],
        parent: QWidget | None = None,
        *,
        draft_sketch_id: str | None = None,
        selected_entity_ids: frozenset[str] = frozenset(),
        selected_segment_indices: dict[str, int] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("对象相切")
        self.first_combo = QComboBox(self)
        self.second_combo = QComboBox(self)
        self.branch_combo = QComboBox(self)
        self.existing_combo = QComboBox(self)
        self.status_label = QLabel("选择图纸中的两个对象，再预览。", self)
        self.status_label.setWordWrap(True)
        self.preview_button = QPushButton("预览", self)
        self.commit_button = QPushButton("确认", self)
        self.cancel_button = QPushButton("取消", self)
        self.remove_button = QPushButton("移除所选关系", self)
        self.canvas_selection_button = QPushButton("在画布选择", self)
        self.relations_by_id = {relation.relation_id: relation for relation in relations}
        branch_labels = {
            "line_left": "直线左侧",
            "line_right": "直线右侧",
            "external": "外切",
            "first_contains_second": "第一曲线包含第二曲线",
            "second_contains_first": "第二曲线包含第一曲线",
        }

        def reference_label(ref: CrossSketchRef) -> str:
            segment = f" / 段 {ref.segment_index + 1}" if ref.segment_index is not None else ""
            return f"{_describe_curve(ref, sketches)}{segment}"

        for relation in relations:
            staged = draft_sketch_id is not None and draft_sketch_id in (
                relation.first.sketch_id,
                relation.second.sketch_id,
            )
            self.existing_combo.addItem(
                f"{'草稿 · ' if staged else ''}{reference_label(relation.first)} ↔ {reference_label(relation.second)} · {branch_labels[relation.branch]}",
                relation.relation_id,
            )
        self.remove_button.setEnabled(bool(relations))
        self.commit_button.setEnabled(False)
        self._previewed: CrossSketchTangency | None = None
        self._draft_sketch_id = draft_sketch_id
        for sketch in sketches:
            for entity in sketch.entities:
                if not sketch.layers.get(entity.layer_name).displayed:
                    continue
                if isinstance(entity, LineEntity | CircleEntity | ArcEntity):
                    self._add_curve(
                        sketch, entity.entity_id, None, type(entity).__name__.removesuffix("Entity")
                    )
                elif isinstance(entity, PolylineEntity):
                    count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
                    for index in range(count):
                        is_arc = bool(entity.bulges) and entity.bulges[index] != 0
                        self._add_curve(
                            sketch, entity.entity_id, index, "圆弧段" if is_arc else "直线段"
                        )
                elif isinstance(entity, RectangleEntity):
                    for index in range(4):
                        self._add_curve(sketch, entity.entity_id, index, "矩形边")
        for label, branch in (
            ("直线左侧", "line_left"),
            ("直线右侧", "line_right"),
            ("外切", "external"),
            ("第一曲线包含第二曲线", "first_contains_second"),
            ("第二曲线包含第一曲线", "second_contains_first"),
        ):
            self.branch_combo.addItem(label, branch)
        if len(selected_entity_ids) == 2:
            candidates = [
                index
                for index in range(self.first_combo.count())
                if isinstance(self.first_combo.itemData(index), CrossSketchRef)
                and self.first_combo.itemData(index).entity_id in selected_entity_ids
                and (
                    self.first_combo.itemData(index).segment_index is None
                    or (selected_segment_indices or {}).get(
                        self.first_combo.itemData(index).entity_id
                    )
                    == self.first_combo.itemData(index).segment_index
                )
            ]
            if (
                len(candidates) == 2
                and frozenset(
                    cast("CrossSketchRef", self.first_combo.itemData(index)).entity_id
                    for index in candidates
                )
                == selected_entity_ids
            ):
                self.first_combo.setCurrentIndex(candidates[0])
                self.second_combo.setCurrentIndex(candidates[1])
                first = cast("CrossSketchRef", self.first_combo.currentData())
                second = cast("CrossSketchRef", self.second_combo.currentData())
                first_owner = next(
                    sketch for sketch in sketches if sketch.sketch_id == first.sketch_id
                )
                second_owner = next(
                    sketch for sketch in sketches if sketch.sketch_id == second.sketch_id
                )
                try:
                    first_curve = resolve_tangent_curve(first_owner, first)
                    second_curve = project_tangent_entity(
                        resolve_tangent_curve(second_owner, second),
                        second_owner.frame,
                        first_owner.frame,
                    )
                    try:
                        branch = infer_tangency_branch(first_curve, second_curve)
                    except ValueError:
                        if isinstance(first_curve, CircleEntity | ArcEntity) and isinstance(
                            second_curve, CircleEntity | ArcEntity
                        ):
                            distance = math.dist(first_curve.center_mm, second_curve.center_mm)
                            if distance <= 1e-12:
                                raise ValueError("同心对象的相切分支不明确。") from None
                            outer = abs(distance - first_curve.radius_mm - second_curve.radius_mm)
                            inner = abs(
                                distance - abs(first_curve.radius_mm - second_curve.radius_mm)
                            )
                            branch = (
                                "external"
                                if outer <= inner or first_curve.radius_mm == second_curve.radius_mm
                                else "first_contains_second"
                                if first_curve.radius_mm > second_curve.radius_mm
                                else "second_contains_first"
                            )
                        else:
                            line = (
                                first_curve if isinstance(first_curve, LineEntity) else second_curve
                            )
                            curve = (
                                second_curve if isinstance(first_curve, LineEntity) else first_curve
                            )
                            if not isinstance(line, LineEntity) or not isinstance(
                                curve, CircleEntity | ArcEntity
                            ):
                                raise
                            dx = line.end_mm[0] - line.start_mm[0]
                            dy = line.end_mm[1] - line.start_mm[1]
                            side = dx * (curve.center_mm[1] - line.start_mm[1]) - dy * (
                                curve.center_mm[0] - line.start_mm[0]
                            )
                            if abs(side) <= 1e-12:
                                raise ValueError("相切侧不明确。") from None
                            branch = "line_left" if side > 0 else "line_right"
                except ValueError as exc:
                    self.branch_combo.setCurrentIndex(-1)
                    self.status_label.setText(str(exc))
                else:
                    self.branch_combo.setCurrentIndex(self.branch_combo.findData(branch))
        form = QFormLayout()
        form.addRow("第一曲线", self.first_combo)
        form.addRow("第二曲线", self.second_combo)
        form.addRow("相切分支", self.branch_combo)
        form.addRow("已有关系", self.existing_combo)
        buttons = QHBoxLayout()
        for button in (
            self.canvas_selection_button,
            self.preview_button,
            self.commit_button,
            self.remove_button,
            self.cancel_button,
        ):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)
        self.preview_button.clicked.connect(self._request_preview)
        self.commit_button.clicked.connect(self._request_commit)
        self.cancel_button.clicked.connect(self.reject)
        self.remove_button.clicked.connect(self._request_removal)
        self.canvas_selection_button.clicked.connect(self.canvas_selection_requested.emit)
        for combo in (self.first_combo, self.second_combo, self.branch_combo):
            combo.currentIndexChanged.connect(self._invalidate)

    def _add_curve(self, sketch: Sketch, entity_id: str, index: int | None, kind: str) -> None:
        ref = CrossSketchRef(sketch.sketch_id, entity_id, index)
        label = f"{kind} · {_describe_curve(ref, (sketch,))}"
        if index is not None:
            label += f" · 段 {index + 1}"
        self.first_combo.addItem(label, ref)
        self.second_combo.addItem(label, ref)

    def _invalidate(self) -> None:
        self._previewed = None
        self.commit_button.setEnabled(False)

    def _request_preview(self) -> None:
        first = self.first_combo.currentData()
        second = self.second_combo.currentData()
        branch = self.branch_combo.currentData()
        try:
            if not isinstance(first, CrossSketchRef) or not isinstance(second, CrossSketchRef):
                raise ValueError("请选择两条曲线。")
            if first.sketch_id == second.sketch_id:
                raise ValueError("请点击“在画布选择”，然后依次选择这两个对象。")
            if not isinstance(branch, str):
                raise ValueError("请选择相切分支。")
            relation = CrossSketchTangency(
                uuid4().hex, first, second, cast("TangencyBranch", branch)
            )
        except ValueError as exc:
            self.status_label.setText(drawing_message(str(exc)))
            return
        self._invalidate()
        self._set_busy(True)
        self.status_label.setText("正在求解预览…")
        self.preview_requested.emit(relation)

    def complete_preview(
        self, relation: CrossSketchTangency, message: str, *, success: bool
    ) -> None:
        self._set_busy(False)
        self.status_label.setText(drawing_message(message))
        self._previewed = relation if success else None
        self.commit_button.setEnabled(success)
        self.preview_completed.emit(success)

    def _request_commit(self) -> None:
        if self._previewed is not None:
            self.commit_button.setEnabled(False)
            self._set_busy(True)
            self.commit_requested.emit(self._previewed)

    def _request_removal(self) -> None:
        identity = self.existing_combo.currentData()
        if isinstance(identity, str):
            self._invalidate()
            self._set_busy(True)
            self.remove_requested.emit(identity)

    def submission_failed(self, message: str) -> None:
        self._invalidate()
        self._set_busy(False)
        self.status_label.setText(drawing_message(message))

    def _set_busy(self, busy: bool) -> None:
        self.canvas_selection_button.setEnabled(not busy)
        self.preview_button.setEnabled(not busy)
        self.remove_button.setEnabled(not busy and self.existing_combo.count() > 0)
        for combo in (self.first_combo, self.second_combo, self.branch_combo, self.existing_combo):
            combo.setEnabled(not busy)
