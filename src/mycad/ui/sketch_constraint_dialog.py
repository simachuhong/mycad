# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicit preview and confirmation UI for persistent sketch constraints."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import cast
from uuid import uuid4

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mycad.core.sketch import (
    CircleEntity,
    LineEntity,
    Point2D,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
    SplineEntity,
)
from mycad.core.sketch_constraints import (
    ConstraintKind,
    ConstraintUnit,
    ReferenceKind,
    SketchConstraint,
    SketchConstraintSolveResult,
    SketchGeometryReference,
)

_CONSTRAINT_LABELS: tuple[tuple[str, str], ...] = (
    ("coincident", "重合"),
    ("horizontal", "水平"),
    ("vertical", "竖直"),
    ("parallel", "平行"),
    ("perpendicular", "垂直"),
    ("tangent", "相切"),
    ("concentric", "同心"),
    ("equal", "相等"),
    ("fixed", "固定点"),
    ("length", "长度"),
    ("distance", "点间距离"),
    ("angle", "角度"),
    ("radius", "半径"),
    ("diameter", "直径"),
)
_REFERENCE_LABELS: tuple[tuple[str, str], ...] = (
    ("geometry", "整个图元"),
    ("start", "起点"),
    ("end", "终点"),
    ("center", "圆心"),
    ("vertex", "顶点"),
    ("segment", "线段"),
)
_TWO_REFERENCE_KINDS = frozenset(
    {
        "coincident",
        "parallel",
        "perpendicular",
        "tangent",
        "concentric",
        "equal",
        "distance",
        "angle",
    }
)
_DIMENSION_UNITS: dict[str, ConstraintUnit] = {
    "length": "mm",
    "distance": "mm",
    "angle": "deg",
    "radius": "mm",
    "diameter": "mm",
}


def _entity_label(index: int, entity: SketchEntity) -> str:
    kind = type(entity).__name__.removesuffix("Entity")
    label = {
        "Point": "点",
        "Line": "直线",
        "Polyline": "多段线",
        "Rectangle": "矩形",
        "Circle": "圆",
        "Arc": "圆弧",
        "Spline": "样条",
    }.get(kind, kind)
    return f"{index + 1}. {label} · {entity.entity_id[:8]}"


def _reference_kinds(entity: SketchEntity) -> tuple[str, ...]:
    if isinstance(entity, PointEntity):
        return ("vertex",)
    if isinstance(entity, SplineEntity):
        return ("start", "end", "vertex")
    if isinstance(entity, LineEntity):
        return ("geometry", "start", "end")
    if isinstance(entity, PolylineEntity | RectangleEntity):
        return ("geometry", "start", "end", "vertex", "segment")
    if isinstance(entity, CircleEntity):
        return ("geometry", "center")
    return ("geometry", "start", "end", "center")


class SketchConstraintDialog(QDialog):
    """Solve one constraint as a preview, then request explicit Bus submission."""

    commit_requested = Signal(object, object, object)
    preview_requested = Signal(object, object, int)
    preview_invalidated = Signal()
    solved_preview = Signal(object)

    def __init__(
        self,
        sketches: tuple[Sketch, ...],
        preview: Callable[[Sketch, SketchConstraint], SketchConstraintSolveResult],
        parent: QWidget | None = None,
        *,
        asynchronous_preview: bool = False,
        preview_update: Callable[[Sketch, SketchConstraint], SketchConstraintSolveResult]
        | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("草图约束")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(680, 440)
        self._sketches = {sketch.sketch_id: sketch for sketch in sketches}
        self._preview = preview
        self._preview_update = preview_update
        self._asynchronous_preview = asynchronous_preview
        self._preview_generation = 0
        self._new_dimension_position: Point2D | None = None
        self._last_candidate: (
            tuple[Sketch, SketchConstraint, SketchConstraintSolveResult] | None
        ) = None

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.sketch_combo = QComboBox()
        for index, sketch in enumerate(sketches):
            self.sketch_combo.addItem(
                f"草图 {index + 1} · {sketch.sketch_id[:8]} · {len(sketch.entities)} 个图元",
                sketch.sketch_id,
            )
        form.addRow("目标草图", self.sketch_combo)

        self.dimension_combo = QComboBox()
        form.addRow("操作", self.dimension_combo)

        self.kind_combo = QComboBox()
        for constraint_id, label in _CONSTRAINT_LABELS:
            self.kind_combo.addItem(label, constraint_id)
        form.addRow("约束", self.kind_combo)

        self.first_entity = QComboBox()
        self.first_reference = self._reference_combo()
        self.first_index = QSpinBox()
        self.first_index.setRange(0, 999)
        self.first_index.setPrefix("索引 ")
        first_row = QHBoxLayout()
        first_row.addWidget(self.first_entity, 2)
        first_row.addWidget(self.first_reference, 1)
        first_row.addWidget(self.first_index, 1)
        form.addRow("引用 A", first_row)

        self.second_entity = QComboBox()
        self.second_reference = self._reference_combo()
        self.second_index = QSpinBox()
        self.second_index.setRange(0, 999)
        self.second_index.setPrefix("索引 ")
        second_row = QHBoxLayout()
        second_row.addWidget(self.second_entity, 2)
        second_row.addWidget(self.second_reference, 1)
        second_row.addWidget(self.second_index, 1)
        self.second_row_widget = QWidget()
        self.second_row_widget.setLayout(second_row)
        self.second_label = QLabel("引用 B")
        form.addRow(self.second_label, self.second_row_widget)

        self.value_field = QDoubleSpinBox()
        self.value_field.setRange(-1_000_000.0, 1_000_000.0)
        self.value_field.setDecimals(6)
        self.value_field.setValue(10.0)
        self.unit_label = QLabel("mm")
        value_row = QHBoxLayout()
        value_row.addWidget(self.value_field)
        value_row.addWidget(self.unit_label)
        self.value_row_widget = QWidget()
        self.value_row_widget.setLayout(value_row)
        self.value_label = QLabel("数值")
        form.addRow(self.value_label, self.value_row_widget)

        self.precision_field = QSpinBox()
        self.precision_field.setRange(0, 8)
        self.precision_field.setValue(2)
        self.scale_field = QDoubleSpinBox()
        self.scale_field.setRange(0.1, 100.0)
        self.scale_field.setDecimals(1)
        self.scale_field.setSingleStep(0.5)
        self.scale_field.setValue(1.0)
        self.scale_field.setSuffix(" ×")
        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("精度"))
        format_row.addWidget(self.precision_field)
        format_row.addSpacing(12)
        format_row.addWidget(QLabel("标注比例"))
        format_row.addWidget(self.scale_field)
        self.format_row_widget = QWidget()
        self.format_row_widget.setLayout(format_row)
        form.addRow("显示", self.format_row_widget)

        self.driving_check = QCheckBox("驱动约束（关闭后仅作为参考关系）")
        self.driving_check.setChecked(True)
        form.addRow("语义", self.driving_check)
        root.addLayout(form)

        self.status_label = QLabel("选择约束和图元后，先预览求解结果。")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(48)
        root.addWidget(self.status_label)
        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        root.addWidget(self.detail_label)
        self.branch_acknowledgement = QCheckBox("已核对方向、所在侧及内外关系变化，接受当前预览")
        self.branch_acknowledgement.hide()
        root.addWidget(self.branch_acknowledgement)

        actions = QHBoxLayout()
        self.preview_button = QPushButton("预览求解")
        self.apply_button = QPushButton("确认添加")
        self.apply_button.setEnabled(False)
        self.cancel_button = QPushButton("取消")
        actions.addStretch(1)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.apply_button)
        actions.addWidget(self.cancel_button)
        root.addLayout(actions)

        self.sketch_combo.currentIndexChanged.connect(self._refresh_entities)
        self.dimension_combo.currentIndexChanged.connect(self._refresh_edit_mode)
        self.kind_combo.currentIndexChanged.connect(self._refresh_kind)
        self.first_entity.currentIndexChanged.connect(self._refresh_reference_options)
        self.second_entity.currentIndexChanged.connect(self._refresh_reference_options)
        self.first_reference.currentIndexChanged.connect(self._invalidate_preview)
        self.second_reference.currentIndexChanged.connect(self._invalidate_preview)
        self.first_index.valueChanged.connect(self._invalidate_preview)
        self.second_index.valueChanged.connect(self._invalidate_preview)
        self.value_field.valueChanged.connect(self._invalidate_preview)
        self.precision_field.valueChanged.connect(self._invalidate_preview)
        self.scale_field.valueChanged.connect(self._invalidate_preview)
        self.driving_check.toggled.connect(self._refresh_dimension_mode)
        self.preview_button.clicked.connect(self.preview_constraint)
        self.apply_button.clicked.connect(self._request_commit)
        self.cancel_button.clicked.connect(self.reject)
        self.branch_acknowledgement.toggled.connect(self._refresh_commit_enabled)
        self._refresh_entities()
        self._refresh_kind()

    def configure_dimensions(self, kind: str = "length", entity_ids: tuple[str, ...] = ()) -> None:
        """Expose annotation kinds and preselect the current canvas selection."""
        self.setWindowTitle("尺寸标注与尺寸驱动")
        for index in range(self.kind_combo.count() - 1, -1, -1):
            if self.kind_combo.itemData(index) not in _DIMENSION_UNITS:
                self.kind_combo.removeItem(index)
        self.kind_combo.setCurrentIndex(self.kind_combo.findData(kind))
        for combo, identity in zip(
            (self.first_entity, self.second_entity), entity_ids, strict=False
        ):
            index = combo.findData(identity)
            if index >= 0:
                combo.setCurrentIndex(index)
        if (
            kind == "distance"
            and self.first_entity.currentData() == self.second_entity.currentData()
        ):
            index = self.second_reference.findData("end")
            if index >= 0:
                self.second_reference.setCurrentIndex(index)
        self.dimension_combo.setItemText(0, "新增尺寸")
        self.driving_check.setText("驱动尺寸：改变几何（取消勾选为参考尺寸，仅测量）")

    def set_dimension_position(self, position: Point2D) -> None:
        """Use the point chosen on the sketch canvas for a new dimension."""
        self._new_dimension_position = position
        self._invalidate_preview()

    @staticmethod
    def _reference_combo() -> QComboBox:
        combo = QComboBox()
        for reference_id, label in _REFERENCE_LABELS:
            combo.addItem(label, reference_id)
        return combo

    def _selected_sketch(self) -> Sketch | None:
        sketch_id = self.sketch_combo.currentData()
        return self._sketches.get(sketch_id) if isinstance(sketch_id, str) else None

    def _selected_entity(self, combo: QComboBox) -> SketchEntity | None:
        sketch = self._selected_sketch()
        entity_id = combo.currentData()
        if sketch is None or not isinstance(entity_id, str):
            return None
        return next((item for item in sketch.entities if item.entity_id == entity_id), None)

    def _refresh_entities(self, _index: int = 0) -> None:
        sketch = self._selected_sketch()
        combos = (self.first_entity, self.second_entity)
        for combo in combos:
            combo.blockSignals(True)
            combo.clear()
            if sketch is not None:
                for index, entity in enumerate(sketch.entities):
                    label = _entity_label(index, entity)
                    if sketch.layers.get(entity.layer_name).locked:
                        label += " · 图层锁定（仅参考尺寸）"
                    combo.addItem(label, entity.entity_id)
            combo.blockSignals(False)
        self._refresh_reference_options()
        self._refresh_dimension_choices()
        self._invalidate_preview()

    def _selected_dimension(self) -> SketchConstraint | None:
        sketch = self._selected_sketch()
        identity = self.dimension_combo.currentData()
        if sketch is None or not isinstance(identity, str):
            return None
        return next((item for item in sketch.constraints if item.constraint_id == identity), None)

    def _refresh_dimension_choices(self) -> None:
        blocker = QSignalBlocker(self.dimension_combo)
        self.dimension_combo.clear()
        self.dimension_combo.addItem("新增约束", None)
        sketch = self._selected_sketch()
        if sketch is not None:
            labels = dict(_CONSTRAINT_LABELS)
            for constraint in sketch.constraints:
                if constraint.kind in _DIMENSION_UNITS:
                    value = "—" if constraint.value is None else f"{constraint.value:g}"
                    mode = "驱动" if constraint.driving else "参考"
                    self.dimension_combo.addItem(
                        f"修改：{labels[constraint.kind]} {value} {constraint.unit} · {mode} · {constraint.constraint_id[:8]}",
                        constraint.constraint_id,
                    )
        del blocker
        self._refresh_edit_mode()

    def _refresh_edit_mode(self, _index: int = 0) -> None:
        dimension = self._selected_dimension()
        references = (
            self.kind_combo,
            self.first_entity,
            self.second_entity,
            self.first_reference,
            self.second_reference,
            self.first_index,
            self.second_index,
        )
        for widget in references:
            widget.setEnabled(dimension is None)
        self.apply_button.setText("确认添加" if dimension is None else "确认修改")
        if dimension is not None:
            blockers = [QSignalBlocker(widget) for widget in references]
            blockers.extend(
                QSignalBlocker(widget)
                for widget in (
                    self.value_field,
                    self.driving_check,
                    self.precision_field,
                    self.scale_field,
                )
            )
            self.kind_combo.setCurrentIndex(self.kind_combo.findData(dimension.kind))
            self._refresh_kind()
            for reference, entity_combo in zip(
                dimension.references, (self.first_entity, self.second_entity), strict=False
            ):
                entity_combo.setCurrentIndex(entity_combo.findData(reference.entity_id))
            self._refresh_reference_options()
            for reference, reference_combo, index_field in zip(
                dimension.references,
                (self.first_reference, self.second_reference),
                (self.first_index, self.second_index),
                strict=False,
            ):
                reference_combo.setCurrentIndex(reference_combo.findData(reference.kind))
                index_field.setValue(reference.index or 0)
            self.value_field.setValue(dimension.value or 0.0)
            self.driving_check.setChecked(dimension.driving)
            self.precision_field.setValue(dimension.precision)
            self.scale_field.setValue(dimension.scale)
            del blockers
        self._refresh_kind()

    def _refresh_reference_options(self, _index: int = 0) -> None:
        for entity_combo, reference_combo in (
            (self.first_entity, self.first_reference),
            (self.second_entity, self.second_reference),
        ):
            entity = self._selected_entity(entity_combo)
            allowed = _reference_kinds(entity) if entity is not None else ()
            kind = self.kind_combo.currentData()
            if kind == "distance":
                allowed = tuple(
                    item for item in allowed if item in {"start", "end", "center", "vertex"}
                )
            elif kind in {"length", "angle"}:
                line_kind = "geometry" if isinstance(entity, LineEntity) else "segment"
                allowed = tuple(item for item in allowed if item == line_kind)
            elif kind in {"radius", "diameter"}:
                allowed = tuple(item for item in allowed if item == "geometry")
            previous = reference_combo.currentData()
            reference_combo.blockSignals(True)
            reference_combo.clear()
            for reference_id, label in _REFERENCE_LABELS:
                if reference_id in allowed:
                    reference_combo.addItem(label, reference_id)
            if any(reference_combo.itemData(i) == previous for i in range(reference_combo.count())):
                reference_combo.setCurrentIndex(
                    next(
                        i
                        for i in range(reference_combo.count())
                        if reference_combo.itemData(i) == previous
                    )
                )
            reference_combo.blockSignals(False)
        self._refresh_index_visibility()
        self._invalidate_preview()

    def _refresh_index_visibility(self) -> None:
        self.first_index.setVisible(self.first_reference.currentData() in ("vertex", "segment"))
        self.second_index.setVisible(self.second_reference.currentData() in ("vertex", "segment"))

    def _refresh_kind(self, _index: int = 0) -> None:
        kind = self.kind_combo.currentData()
        self.second_label.setVisible(kind in _TWO_REFERENCE_KINDS)
        self.second_row_widget.setVisible(kind in _TWO_REFERENCE_KINDS)
        unit = _DIMENSION_UNITS.get(kind)
        self.value_label.setVisible(unit is not None)
        self.value_row_widget.setVisible(unit is not None)
        self.format_row_widget.setVisible(unit is not None)
        if unit == "mm":
            self.value_field.setRange(0.000001, 1_000_000.0)
            self.value_field.setValue(max(0.000001, self.value_field.value()))
        else:
            self.value_field.setRange(-360.0, 360.0)
        self.unit_label.setText("°" if unit == "deg" else "mm")
        self._refresh_reference_options()
        self._refresh_dimension_mode()
        self._invalidate_preview()

    def _refresh_dimension_mode(self, *_args: object) -> None:
        is_dimension = self.kind_combo.currentData() in _DIMENSION_UNITS
        if not is_dimension and not self.driving_check.isChecked():
            blocker = QSignalBlocker(self.driving_check)
            self.driving_check.setChecked(True)
            del blocker
        self.driving_check.setEnabled(is_dimension)
        self.driving_check.setText(
            "驱动尺寸（关闭后显示实测参考值）" if is_dimension else "驱动几何关系"
        )
        is_reference_dimension = is_dimension and not self.driving_check.isChecked()
        self.value_field.setReadOnly(is_reference_dimension)
        self.value_field.setToolTip(
            "参考尺寸由当前几何测量得出。" if is_reference_dimension else "驱动尺寸值参与草图求解。"
        )
        self._invalidate_preview()

    def _reference(
        self, entity_combo: QComboBox, kind_combo: QComboBox, index: QSpinBox
    ) -> SketchGeometryReference:
        entity_id = entity_combo.currentData()
        reference_kind = kind_combo.currentData()
        if not isinstance(entity_id, str) or not isinstance(reference_kind, str):
            raise ValueError("请先选择有效的图元引用。")
        reference = cast("ReferenceKind", reference_kind)
        return SketchGeometryReference(
            entity_id,
            reference,
            index.value() if reference in ("vertex", "segment") else None,
        )

    def _constraint(self) -> SketchConstraint:
        existing = self._selected_dimension()
        if existing is not None:
            return replace(
                existing,
                value=self.value_field.value() if self.driving_check.isChecked() else None,
                driving=self.driving_check.isChecked(),
                precision=self.precision_field.value(),
                scale=self.scale_field.value(),
            )
        raw_kind = self.kind_combo.currentData()
        if not isinstance(raw_kind, str):
            raise ValueError("请选择约束类型。")
        kind = cast("ConstraintKind", raw_kind)
        references = [self._reference(self.first_entity, self.first_reference, self.first_index)]
        if kind in _TWO_REFERENCE_KINDS:
            references.append(
                self._reference(self.second_entity, self.second_reference, self.second_index)
            )
        unit = _DIMENSION_UNITS.get(kind)
        return SketchConstraint(
            uuid4().hex,
            kind,
            tuple(references),
            self.value_field.value()
            if unit is not None and self.driving_check.isChecked()
            else None,
            unit,
            self.driving_check.isChecked(),
            "user",
            self.precision_field.value(),
            self.scale_field.value(),
            position_mm=self._new_dimension_position if unit is not None else None,
        )

    def _invalidate_preview(self, *_args: object) -> None:
        self._preview_generation += 1
        self._last_candidate = None
        self.branch_acknowledgement.setChecked(False)
        self.branch_acknowledgement.hide()
        self.apply_button.setEnabled(False)
        self.detail_label.clear()
        if hasattr(self, "status_label"):
            self.status_label.setText("输入已更改；请重新预览求解结果。")
        self.preview_invalidated.emit()

    def preview_constraint(self) -> None:
        sketch = self._selected_sketch()
        if sketch is None:
            self.status_label.setText("当前没有可用草图。")
            return
        try:
            constraint = self._constraint()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._invalidate_preview()
        generation = self._preview_generation
        if self._asynchronous_preview:
            self.status_label.setText("正在求解草图并预览下游特征重建…")
            self.preview_requested.emit(sketch, constraint, generation)
        else:
            preview = self._preview if self._selected_dimension() is None else self._preview_update
            result = (
                preview(sketch, constraint)
                if preview is not None
                else SketchConstraintSolveResult(
                    "invalid", None, None, message="未配置尺寸修改预览服务。"
                )
            )
            self.complete_preview(generation, sketch, constraint, result)

    def complete_preview(
        self,
        generation: int,
        sketch: Sketch,
        constraint: SketchConstraint,
        result: SketchConstraintSolveResult,
    ) -> bool:
        """Accept only a result for the latest, unchanged dialog inputs."""
        if generation != self._preview_generation:
            return False
        self._last_candidate = (sketch, constraint, result)
        self.branch_acknowledgement.setChecked(False)
        self.branch_acknowledgement.setVisible(bool(result.branch_changes))
        self._refresh_commit_enabled()
        status = self._status_text(result)
        if result.status == "success" and not constraint.driving and result.sketch is not None:
            measured_constraint = next(
                item
                for item in result.sketch.constraints
                if item.constraint_id == constraint.constraint_id
            )
            if measured_constraint.value is not None:
                blocker = QSignalBlocker(self.value_field)
                self.value_field.setValue(measured_constraint.value)
                del blocker
                status += f" 参考值：{measured_constraint.value:.6g} {measured_constraint.unit}."
        self.status_label.setText(status)
        self.detail_label.setText(self._detail_text(sketch, constraint, result))
        self.solved_preview.emit(result)
        return True

    def _refresh_commit_enabled(self) -> None:
        candidate = self._last_candidate
        self.apply_button.setEnabled(
            candidate is not None
            and candidate[2].status == "success"
            and (not candidate[2].branch_changes or self.branch_acknowledgement.isChecked())
            and self.cancel_button.isEnabled()
        )

    @staticmethod
    def _status_text(result: SketchConstraintSolveResult) -> str:
        messages = {
            "success": f"求解成功 · 剩余自由度 {result.degrees_of_freedom}。零自由度不代表解唯一。",
            "failed": "求解失败；当前草图与历史保持不变。",
            "invalid": "约束引用或输入无效；请修正图元引用后重试。",
            "unavailable": "当前平台未安装可用的约束求解器；未写入任何变更。",
        }
        status = result.message or messages[result.status]
        if result.branch_changes:
            status += " 检测到分支变化，请核对预览中的相关图元后确认。"
        return status

    @staticmethod
    def _detail_text(
        sketch: Sketch, pending: SketchConstraint, result: SketchConstraintSolveResult
    ) -> str:
        constraints = {item.constraint_id: item for item in (*sketch.constraints, pending)}
        entities = {
            entity.entity_id: _entity_label(index, entity)
            for index, entity in enumerate(sketch.entities)
        }
        relation_labels = dict(_CONSTRAINT_LABELS)
        reference_labels = dict(_REFERENCE_LABELS)

        def describe(identity: str) -> str:
            constraint = constraints.get(identity)
            if constraint is None:
                return f"约束 {identity[:8]}（引用不可用）"
            references: list[str] = []
            for reference in constraint.references:
                index = "" if reference.index is None else f" {reference.index + 1}"
                references.append(
                    f"{entities.get(reference.entity_id, reference.entity_id[:8])} · "
                    f"{reference_labels[reference.kind]}{index}"
                )
            return f"{relation_labels[constraint.kind]} {identity[:8]}（{'；'.join(references)}）"

        details: list[str] = []
        if result.conflicting_constraint_ids:
            details.append(
                "相关冲突："
                + "、".join(describe(item) for item in result.conflicting_constraint_ids)
            )
        if result.redundant_constraint_ids:
            details.append(
                "冗余关系：" + "、".join(describe(item) for item in result.redundant_constraint_ids)
            )
        details.extend(
            f"{change.message} · 图元 {'、'.join(identity[:8] for identity in change.entity_ids)}"
            for change in result.branch_changes
        )
        return "\n".join(details)

    def _request_commit(self) -> None:
        if self._last_candidate is None:
            self.status_label.setText("请先预览；修改输入后需要重新求解。")
            return
        sketch, constraint, result = self._last_candidate
        if result.status != "success":
            self.status_label.setText("只有求解成功的预览才能确认。")
            return
        if result.branch_changes and not self.branch_acknowledgement.isChecked():
            self.status_label.setText("请先核对分支变化并勾选接受当前预览。")
            return
        self.apply_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.status_label.setText("正在通过命令历史提交约束…")
        self.commit_requested.emit(sketch, constraint, result)

    def submission_failed(self, message: str, *, invalidate_preview: bool = False) -> None:
        if invalidate_preview:
            self._invalidate_preview()
        self.cancel_button.setEnabled(True)
        self._refresh_commit_enabled()
        self.status_label.setText(f"提交失败：{message}。草图历史未改变。")
