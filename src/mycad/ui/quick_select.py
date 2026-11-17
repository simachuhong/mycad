# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Quick selection of visible 2D sketch entities."""

from __future__ import annotations

import math

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QWidget,
)

from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    SketchEntity,
    SplineEntity,
)

_TYPES = (
    ("直线", LineEntity),
    ("圆", CircleEntity),
    ("圆弧", ArcEntity),
    ("矩形", RectangleEntity),
    ("多段线", PolylineEntity),
    ("样条曲线", SplineEntity),
    ("点", PointEntity),
)
_POLYGON_KIND = "多边形（闭合直线多段线）"


class QuickSelectDialog(QDialog):
    """Choose a scope, type, layer and inclusion mode for visible entities."""

    def __init__(
        self,
        entities: tuple[SketchEntity, ...],
        parent: QWidget | None = None,
        *,
        dimensions: tuple[tuple[str, str], ...] = (),
        dimension_values: dict[str, tuple[float, str]] | None = None,
        images: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(parent)
        self.dimensions = dimensions
        self.dimension_values = dimension_values or {}
        self.images = images
        self.setWindowTitle("快速选择")
        layout = QFormLayout(self)
        layout.addRow(QLabel("筛选可见二维图元、尺寸标注和图片。"))
        self.scope = QComboBox()
        self.scope.addItems(("全部可见图元", "当前选中图元"))
        layout.addRow("范围", self.scope)
        self.kind = QComboBox()
        self.kind.addItems(
            ("所有类型", *(name for name, _type in _TYPES), _POLYGON_KIND, "尺寸标注", "图片")
        )
        self.kind.setToolTip("多边形包括所有由直线组成的闭合多段线。")
        layout.addRow("类型", self.kind)
        self.layer = QComboBox()
        self.layer.addItem("所有图层", None)
        layers: dict[str, str] = {}
        for name in (
            *(entity.layer_name for entity in entities),
            *(layer for _, layer in (*dimensions, *images)),
        ):
            layers.setdefault(name.casefold(), name)
        for name in sorted(layers.values(), key=str.casefold):
            self.layer.addItem(name, name)
        layout.addRow("图层", self.layer)
        self.attribute = QComboBox()
        self.attribute.setObjectName("quickSelectAttribute")
        self.attribute.addItems(
            ("不限制", "直线长度", "圆/圆弧半径", "尺寸测量值（mm）", "尺寸测量值（°）")
        )
        self.attribute.setToolTip("尺寸筛选使用原始测量值，不受显示比例或文字覆盖影响。")
        layout.addRow("数值属性", self.attribute)
        self.operator = QComboBox()
        self.operator.setObjectName("quickSelectOperator")
        self.operator.addItems(("等于", "不等于", "大于", "小于"))
        layout.addRow("比较", self.operator)
        self.threshold = QDoubleSpinBox()
        self.threshold.setObjectName("quickSelectThreshold")
        self.threshold.setRange(-1e9, 1e9)
        self.threshold.setDecimals(6)
        self.threshold.setSuffix(" mm")
        layout.addRow("数值", self.threshold)
        self.attribute.currentIndexChanged.connect(self._sync_numeric_controls)
        self._sync_numeric_controls()
        self.mode = QComboBox()
        self.mode.addItems(("包含匹配对象", "排除匹配对象"))
        layout.addRow("匹配方式", self.mode)
        self.append = QCheckBox("追加到当前选择")
        layout.addRow(self.append)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        ok_button.setText("确定")
        cancel_button.setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _sync_numeric_controls(self) -> None:
        enabled = self.attribute.currentIndex() != 0
        self.operator.setEnabled(enabled)
        self.threshold.setEnabled(enabled)
        self.threshold.setSuffix(
            " °" if self.attribute.currentText() == "尺寸测量值（°）" else " mm"
        )

    def _compare_numeric(self, value: float) -> bool:
        threshold = self.threshold.value()
        equal = math.isclose(value, threshold, rel_tol=0.0, abs_tol=1e-9)
        return {
            "等于": equal,
            "不等于": not equal,
            "大于": value > threshold and not equal,
            "小于": value < threshold and not equal,
        }[self.operator.currentText()]

    def _matches_numeric(self, entity: SketchEntity) -> bool:
        attribute = self.attribute.currentText()
        if attribute == "不限制":
            return True
        if attribute == "直线长度" and isinstance(entity, LineEntity):
            value = math.dist(entity.start_mm, entity.end_mm)
        elif attribute == "圆/圆弧半径" and isinstance(entity, CircleEntity | ArcEntity):
            value = entity.radius_mm
        else:
            return False
        return self._compare_numeric(value)

    def _matches_layer(self, name: str) -> bool:
        selected: object = self.layer.currentData()
        return selected is None or (
            isinstance(selected, str) and selected.casefold() == name.casefold()
        )

    def matching_ids(
        self, entities: tuple[SketchEntity, ...], selected: frozenset[str]
    ) -> frozenset[str]:
        candidates = tuple(
            entity
            for entity in entities
            if self.scope.currentIndex() == 0 or entity.entity_id in selected
        )
        kind = self.kind.currentText()
        matches = {
            entity.entity_id
            for entity in candidates
            if (
                kind == "所有类型"
                or (
                    kind == _POLYGON_KIND
                    and isinstance(entity, PolylineEntity)
                    and entity.closed
                    and len(entity.points_mm) >= 3
                    and not any(entity.bulges)
                )
                or any(name == kind and type(entity) is cls for name, cls in _TYPES)
            )
            and self._matches_layer(entity.layer_name)
            and self._matches_numeric(entity)
        }
        if self.mode.currentIndex() == 1:
            matches = {entity.entity_id for entity in candidates} - matches
        return frozenset(matches)

    def matching_annotations(
        self, items: tuple[tuple[str, str], ...], selected: frozenset[str], kind: str
    ) -> frozenset[str]:
        candidates = {
            identity: layer
            for identity, layer in items
            if self.scope.currentIndex() == 0 or identity in selected
        }
        matches = {
            identity
            for identity, layer in candidates.items()
            if self.kind.currentText() in ("所有类型", kind)
            and self._matches_layer(layer)
            and (
                self.attribute.currentIndex() == 0
                or (
                    kind == "尺寸标注"
                    and (measurement := self.dimension_values.get(identity)) is not None
                    and (self.attribute.currentText(), measurement[1])
                    in (("尺寸测量值（mm）", "mm"), ("尺寸测量值（°）", "deg"))
                    and self._compare_numeric(measurement[0])
                )
            )
        }
        if self.mode.currentIndex() == 1:
            matches = set(candidates) - matches
        return frozenset(matches)
