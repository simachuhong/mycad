# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Read-only drafting tree with stable identities and selection requests."""

from __future__ import annotations

from typing import override

from PySide6.QtCore import QEvent, QItemSelectionModel, QObject, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mycad.core.sketch import Sketch
from mycad.core.sketch_constraints import DIMENSION_KINDS, SketchConstraint

KIND_ROLE = int(Qt.ItemDataRole.UserRole)
ID_ROLE = KIND_ROLE + 1

_ENTITY_NAMES = {
    "LineEntity": "直线",
    "CircleEntity": "圆",
    "ArcEntity": "圆弧",
    "PolylineEntity": "多段线",
    "RectangleEntity": "矩形",
    "SplineEntity": "样条",
}
_CONSTRAINT_NAMES = {
    "coincident": "重合",
    "horizontal": "水平",
    "vertical": "垂直",
    "parallel": "平行",
    "perpendicular": "垂直关系",
    "tangent": "相切",
    "concentric": "同心",
    "equal": "相等",
    "fixed": "固定",
    "length": "长度",
    "distance": "距离",
    "angle": "角度",
    "radius": "半径",
    "diameter": "直径",
    "arc_length": "弧长",
}


def _constraint_label(constraint: SketchConstraint) -> str:
    name = _CONSTRAINT_NAMES[constraint.kind]
    if constraint.kind in {"length", "distance"}:
        name = {
            "horizontal": "水平尺寸",
            "vertical": "垂直尺寸",
            "ordinate_x": "X 坐标",
            "ordinate_y": "Y 坐标",
        }.get(constraint.axis, name)
    if constraint.value is not None:
        name += f" {constraint.value:.{constraint.precision}f} {constraint.unit}"
    return name


class SketchNavigator(QWidget):
    """Display sketches without mutating their geometry, layers or history."""

    selection_requested = Signal(object, object)
    constraint_activated = Signal(str)
    delete_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tree = QTreeWidget()
        self.tree.setObjectName("draftingNavigationTree")
        self.tree.installEventFilter(self)
        self.tree.setHeaderLabels(("图形", "图层 / 状态"))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(self._activate)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)
        self._signature: tuple[tuple[Sketch, ...], frozenset[str], frozenset[str]] | None = None
        self._items: dict[tuple[str, str], QTreeWidgetItem] = {}

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.tree
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Delete
        ):
            self.delete_requested.emit()
            return True
        return super().eventFilter(watched, event)

    def sync(
        self,
        sketches: tuple[Sketch, ...],
        selected_entities: frozenset[str],
        selected_constraints: frozenset[str],
        selectable_entities: frozenset[str],
        selectable_constraints: frozenset[str],
    ) -> None:
        signature = (sketches, selectable_entities, selectable_constraints)
        with QSignalBlocker(self.tree):
            if signature != self._signature:
                expansion = {key: item.isExpanded() for key, item in self._items.items()}
                scroll = self.tree.verticalScrollBar().value()
                current = self.tree.currentItem()
                current_key: tuple[str, str] | None = None
                if current is not None:
                    kind, identity = current.data(0, KIND_ROLE), current.data(0, ID_ROLE)
                    if isinstance(kind, str) and isinstance(identity, str):
                        current_key = (kind, identity)
                current_column = self.tree.currentColumn()
                self._items.clear()
                self.tree.clear()
                for index, sketch in enumerate(sketches):
                    title = "当前草稿" if index == 0 else f"草图 {index} · {sketch.sketch_id[:8]}"
                    root = self._add(None, "group", sketch.sketch_id, title, "", True)
                    entities = self._add(
                        root,
                        "group",
                        sketch.sketch_id + "/entities",
                        f"图元 ({len(sketch.entities)})",
                        "",
                        True,
                    )
                    for number, entity in enumerate(sketch.entities, 1):
                        self._add(
                            entities,
                            "entity",
                            entity.entity_id,
                            f"{_ENTITY_NAMES[type(entity).__name__]} {number}",
                            entity.layer_name,
                            entity.entity_id in selectable_entities,
                        )
                    constraints = self._add(
                        root,
                        "group",
                        sketch.sketch_id + "/constraints",
                        f"约束与尺寸 ({len(sketch.constraints)})",
                        "",
                        True,
                    )
                    for constraint in sketch.constraints:
                        state = (
                            ("驱动" if constraint.driving else "参考")
                            if constraint.kind in DIMENSION_KINDS
                            else "几何关系"
                        )
                        self._add(
                            constraints,
                            "constraint",
                            constraint.constraint_id,
                            _constraint_label(constraint),
                            state,
                            constraint.constraint_id in selectable_constraints,
                        )
                for key, item in self._items.items():
                    if key[0] == "group":
                        item.setExpanded(expansion.get(key, True))
                if current_key is not None and current_key in self._items:
                    self.tree.setCurrentItem(
                        self._items[current_key],
                        current_column,
                        QItemSelectionModel.SelectionFlag.NoUpdate,
                    )
                self.tree.verticalScrollBar().setValue(scroll)
                self._signature = signature
            for (kind, identity), item in self._items.items():
                selected = (kind == "entity" and identity in selected_entities) or (
                    kind == "constraint" and identity in selected_constraints
                )
                item.setSelected(selected and bool(item.flags() & Qt.ItemFlag.ItemIsSelectable))

    def _add(
        self,
        parent: QTreeWidgetItem | None,
        kind: str,
        identity: str,
        title: str,
        detail: str,
        selectable: bool,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([title, detail])
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        item.setData(0, KIND_ROLE, kind)
        item.setData(0, ID_ROLE, identity)
        item.setToolTip(
            0, identity if selectable else "当前工作平面不可选择，或对象所在图层已隐藏/冻结。"
        )
        if kind == "group" or not selectable:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        if not selectable:
            item.setDisabled(True)
        self._items[(kind, identity)] = item
        return item

    def _selection_changed(self) -> None:
        entities: set[str] = set()
        constraints: set[str] = set()
        for item in self.tree.selectedItems():
            identity = item.data(0, ID_ROLE)
            if isinstance(identity, str):
                if item.data(0, KIND_ROLE) == "entity":
                    entities.add(identity)
                elif item.data(0, KIND_ROLE) == "constraint":
                    constraints.add(identity)
        self.selection_requested.emit(frozenset(entities), frozenset(constraints))

    def _activate(self, item: QTreeWidgetItem, _column: int) -> None:
        identity = item.data(0, ID_ROLE)
        if (
            item.data(0, KIND_ROLE) == "constraint"
            and isinstance(identity, str)
            and item.flags() & Qt.ItemFlag.ItemIsSelectable
        ):
            self.constraint_activated.emit(identity)
