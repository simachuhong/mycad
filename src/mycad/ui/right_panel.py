# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Right dock five fixed tabs: structure / properties / options / display / measure.

- 「结构」树：文档根节点（part_name，文件名 stem 落 tooltip——F-TREE-01）→
  基准/草图/特征/实体 四分组；阶段 1 数据源 = ``Document.feature_history``
  （特征组，只读、不经 Bus）与 ``named_groups``（实体组，只读）；基准/草图
  组空显示占位文案。特征叶点击发 ``structure_selection_changed(ord)``
  （todo 10 双向联动入口）并联动属性表。
- 「属性」只读表：选中命令 → spec 参数（参数名/类型/当前值）；无选中 →
  文档级 metadata 六键只读表（F-PROP-01）。属性表不做编辑。
- 「选项」参数编辑表：数据源 = todo 6 :class:`PlanDraftController`（本 todo
  绑定真实控制器；todo 12 在计划确认流中接线）。``selected_step_index``
  是「编辑哪一步」的唯一答案；单元格编辑 → 解析 JSON（失败按原字符串）
  → ``set_params``；校验失败回滚单元格并发 ``options_error``，不做空捕获。
- 「显示」「测量」占位页：disabled 说明文字（初稿 §6）。

预留约定 API（初稿 §6）：``register_right_tab``——外部（含插件）向右栏追加
自定义 Tab 的入口。阶段 1 不实现（与 register_left_item 同款：仅固定命名与
语义：调用方提供 (widget, 标题)，面板追加为一页，不参与五固定页断言），
开放与否留后续阶段决定。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mycad.commands.registry import CommandRegistry
from mycad.core.document import METADATA_KEYS, Document, PlannedCommand
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import LoadedDocument
from mycad.ui.plan_draft import PlanDraftController

#: 五固定页顺序即 addTab 顺序（测试钉住）。
RIGHT_TAB_TITLES: tuple[str, ...] = ("结构", "属性", "选项", "显示", "测量")

#: 结构树四分组（初稿 §6；基准/草图阶段 1 恒为占位）。
STRUCTURE_GROUP_TITLES: tuple[str, ...] = ("基准", "草图", "特征", "实体")
FEATURE_GROUP_TITLE: str = "特征"
SOLIDS_GROUP_TITLE: str = "实体"
EMPTY_PROMPT: str = "（空）"
UNTITLED_DOCUMENT: str = "未命名文档"

#: 结构叶子的角色槽：UserRole 存 feature_history ordinal。
ORDINAL_ROLE: int = int(Qt.ItemDataRole.UserRole)


def _properties_of(schema: Mapping[str, object]) -> dict[str, object]:
    """取 schema 的 ``properties`` 段；JSON-schema 值是无类型 dict，统一在此收口
    成 ``dict[str, object]``（调用方只做键名/类型标注读取，不做结构判断）。"""
    properties = schema.get("properties")
    if isinstance(properties, dict):
        return cast("dict[str, object]", properties)
    return {}


def _default_label(prop: object) -> object:
    """spec 参数的 schema 默认值；无则 None（_value_label 渲染为 —）。"""
    if not isinstance(prop, dict):
        return None
    return cast("dict[str, object]", prop).get("default")


def _type_label(prop: object) -> str:
    """参数类型列：$ref 取最后段（如 ``#/$defs/Positive`` → ``Positive``）。"""
    if not isinstance(prop, dict):
        return "—"
    record = cast("dict[str, object]", prop)
    ref = record.get("$ref")
    if isinstance(ref, str):
        return ref.rsplit("/", 1)[-1]
    declared = record.get("type")
    return declared if isinstance(declared, str) else "—"


def _value_label(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return str(value)
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)


def _set_row_count(table: QTableWidget, count: int) -> None:
    while table.rowCount() > count:
        table.removeRow(table.rowCount() - 1)
    while table.rowCount() < count:
        table.insertRow(table.rowCount())


class RightPanel(QWidget):
    """右栏五页容器；文档数据经 ``bind_document``，草稿经 ``bind_draft``。"""

    structure_selection_changed = Signal(int)
    options_error = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._registry: CommandRegistry | None = None
        self._document: Document | None = None
        self._draft: PlanDraftController | None = None
        self._document_name: str | None = None
        self._options_key_by_row: list[str] = []
        self._filling_options = False

        self._tabs = QTabWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)

        self._structure_tree = QTreeWidget()
        self._structure_tree.setHeaderLabels(("结构",))
        self._structure_tree.itemClicked.connect(self._on_structure_item_clicked)

        self._property_table = QTableWidget(0, 3)
        self._property_table.setHorizontalHeaderLabels(("参数", "类型", "当前值"))
        # 只读（计划 todo 7："属性表不做编辑"）。
        self._property_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._property_table.horizontalHeader().setStretchLastSection(True)
        self._property_table.verticalHeader().setVisible(False)

        self._options_table = QTableWidget(0, 2)
        self._options_table.setHorizontalHeaderLabels(("参数", "当前值"))
        self._options_table.horizontalHeader().setStretchLastSection(True)
        self._options_table.verticalHeader().setVisible(False)
        self._options_table.itemChanged.connect(self._on_options_item_changed)

        self._tabs.addTab(self._structure_tree, RIGHT_TAB_TITLES[0])
        self._tabs.addTab(self._property_table, RIGHT_TAB_TITLES[1])
        self._tabs.addTab(self._options_table, RIGHT_TAB_TITLES[2])
        self._display_tab = self._placeholder_tab("显示控制占用位（后续阶段）")
        self._measure_tab = self._placeholder_tab("测量功能占用位（后续阶段）")
        self._tabs.addTab(self._display_tab, RIGHT_TAB_TITLES[3])
        self._tabs.addTab(self._measure_tab, RIGHT_TAB_TITLES[4])
        for index in (self._tabs.indexOf(self._display_tab), self._tabs.indexOf(self._measure_tab)):
            self._tabs.setTabEnabled(index, False)

        self._show_document_properties()

    # ------------------------------------------------------------------ API

    @property
    def tabs(self) -> QTabWidget:
        """只读访问五页容器（占位页禁用态的断言由此发出）。"""
        return self._tabs

    @property
    def structure_tree(self) -> QTreeWidget:
        """只读访问结构树（窗口层与测试经公开访问器取用）。"""
        return self._structure_tree

    @property
    def property_table(self) -> QTableWidget:
        """只读访问属性表。"""
        return self._property_table

    @property
    def options_table(self) -> QTableWidget:
        """只读访问选项编辑表（todo 12 确认流需要对它注入焦点/取行）。"""
        return self._options_table

    def bind_document(
        self, loaded: LoadedDocument, registry: CommandRegistry, *, document_stem: str | None = None
    ) -> None:
        """绑定单文档视图（结构树 + 文档级属性）。

        ``document_stem`` 由窗口层在打开文档时传入（LoadedDocument 不携带
        路径）；未传则以 "未命名文档" 作根。
        """
        self._registry = registry
        self._document = loaded.document
        self._document_name = document_stem
        self.refresh_structure()
        self._show_document_properties()

    def bind_draft(self, draft: PlanDraftController) -> None:
        """绑定草稿控制器；选项表随信号自动重填。"""
        self._draft = draft
        draft.params_changed.connect(self._on_draft_params_changed)
        draft.plan_replaced.connect(self._refill_options)
        self._refill_options()

    def refresh_structure(self) -> None:
        """重建结构树（named_group_added/removed 等信号由窗口层转发到这里）。"""
        if self._document is None:
            return
        tree = self._structure_tree
        tree.clear()
        metadata = self._document.metadata
        part_name = metadata.get("part_name")
        label = part_name if isinstance(part_name, str) and part_name else UNTITLED_DOCUMENT
        root = QTreeWidgetItem(tree, [label])
        if self._document_name:
            root.setToolTip(0, self._document_name)
        for title in STRUCTURE_GROUP_TITLES:
            group = QTreeWidgetItem(root, [title])
            if title == FEATURE_GROUP_TITLE:
                for command in self._document.commands:
                    leaf = QTreeWidgetItem(
                        group,
                        [
                            f"#{command.ordinal} {_readable_name(self._registry, command.id)}"
                            f"（{command.id}）"
                        ],
                    )
                    leaf.setData(0, ORDINAL_ROLE, int(command.ordinal))
            elif title == SOLIDS_GROUP_TITLE:
                for name in self._document.named_groups:
                    QTreeWidgetItem(group, [name])
            if group.childCount() == 0:
                QTreeWidgetItem(group, [EMPTY_PROMPT])
        tree.expandAll()

    def show_spec_params(self, spec_id: str) -> None:
        """显示某 spec 的参数原型（类型列来自 schema，值列为默认值/—）。"""
        spec = self._registry.get(spec_id) if self._registry is not None else None
        if spec is None:
            return
        rows: list[tuple[str, str, str]] = []
        for key, prop in _properties_of(spec.params_schema).items():
            rows.append((key, _type_label(prop), _value_label(_default_label(prop))))
        self._fill_property_table(rows)

    def _on_structure_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        ordinal = item.data(0, ORDINAL_ROLE)
        if not isinstance(ordinal, int) or isinstance(ordinal, bool):
            return
        self.structure_selection_changed.emit(ordinal)
        self._show_properties_for_ordinal(ordinal)

    def _show_properties_for_ordinal(self, ordinal: int) -> None:
        if self._document is None:
            return
        for command in self._document.commands:
            if command.ordinal == ordinal:
                self.show_command_properties(command.id, command.params)
                return

    def select_feature_ordinal(self, ordinal: int | None) -> None:
        """视口→树方向（todo 10）：编程式选中对应特征叶并联动属性表。

        与用户点击不同，这里**不**再发 ``structure_selection_changed``——
        树→视口才是信号方向，视口→树由本方法直接落地，避免回环。
        ``None`` 清除树选中，属性表回到文档级 metadata 视图。
        """
        tree = self._structure_tree
        if ordinal is None:
            # Qt 的 setCurrentItem(None) 会清空选中，但 PySide stub 把参数定
            # 型为非 None；clearSelection 是同一个视觉效果的类型安全写法。
            tree.clearSelection()
            tree.setCurrentIndex(QModelIndex())
            self._show_document_properties()
            return
        item = self._find_ordinal_item(tree.invisibleRootItem(), ordinal)
        if item is not None:
            tree.setCurrentItem(item)
            tree.scrollToItem(item)
        self._show_properties_for_ordinal(ordinal)

    def _find_ordinal_item(
        self, item: QTreeWidgetItem | None, ordinal: int
    ) -> QTreeWidgetItem | None:
        """递归找 ORDINAL_ROLE == ordinal 的叶节点。"""
        if item is None:
            return None
        for index in range(item.childCount()):
            child = item.child(index)
            if child is None:  # Qt stubs type child(index) as QTreeWidgetItem | None
                continue
            data = child.data(0, ORDINAL_ROLE)
            if isinstance(data, int) and not isinstance(data, bool) and data == ordinal:
                return child
            found = self._find_ordinal_item(child, ordinal)
            if found is not None:
                return found
        return None

    def show_command_properties(self, command_id: str, params: Mapping[str, object]) -> None:
        spec = self._registry.get(command_id) if self._registry is not None else None
        if spec is None:
            return
        rows = [
            (key, _type_label(prop), _value_label(params.get(key)))
            for key, prop in _properties_of(spec.params_schema).items()
        ]
        self._fill_property_table(rows)

    def _fill_property_table(self, rows: Sequence[tuple[str, str, str]]) -> None:
        _set_row_count(self._property_table, len(rows))
        for row, (key, typ, value) in enumerate(rows):
            self._property_table.setItem(row, 0, QTableWidgetItem(key))
            self._property_table.setItem(row, 1, QTableWidgetItem(typ))
            self._property_table.setItem(row, 2, QTableWidgetItem(value))
        self._property_table.resizeColumnsToContents()

    def _show_document_properties(self) -> None:
        if self._document is None:
            rows: list[tuple[str, str, str]] = [(key, "字符串", "—") for key in METADATA_KEYS]
        else:
            metadata = self._document.metadata
            rows = [(key, "字符串", _value_label(metadata.get(key))) for key in METADATA_KEYS]
        self._fill_property_table(rows)

    def _on_draft_params_changed(self, step: int, params: dict[str, Any]) -> None:
        self._refill_options()

    def _refill_options(self) -> None:
        if self._draft is None:
            _set_row_count(self._options_table, 0)
            self._options_key_by_row = []
            return
        steps = self._draft.steps()
        index = self._draft.selected_step_index()
        if not 0 <= index < len(steps):
            _set_row_count(self._options_table, 0)
            self._options_key_by_row = []
            return
        params = self._draft.params_of(steps[index])
        self._options_key_by_row = list(params)
        self._filling_options = True
        try:
            _set_row_count(self._options_table, len(params))
            for row, (key, value) in enumerate(params.items()):
                self._options_table.setItem(row, 0, QTableWidgetItem(key))
                self._options_table.setItem(row, 1, QTableWidgetItem(_value_label(value)))
            self._options_table.resizeColumnsToContents()
        finally:
            self._filling_options = False

    def _on_options_item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling_options or self._draft is None:
            return
        step = self._current_step()
        if step is None:
            return
        key = self._options_key_by_row[item.row()]
        old = self._draft.params_of(step)
        try:
            parsed: object = json.loads(item.text())
        except json.JSONDecodeError:
            parsed = item.text()
        new_params: dict[str, object] = dict(old)
        new_params[key] = parsed
        try:
            self._draft.set_params(step, new_params)
        except ValidationError as exc:
            self.options_error.emit(f"{key}：{str(exc)[:160]}")
            self._refill_options()  # 校验失败回滚单元格（不做空捕获）

    def _current_step(self) -> PlannedCommand | None:
        if self._draft is None:
            return None
        steps = self._draft.steps()
        index = self._draft.selected_step_index()
        if steps and 0 <= index < len(steps):
            return steps[index]
        return None

    def _placeholder_tab(self, text: str) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        label = QLabel(text, page)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        return page


def _readable_name(registry: CommandRegistry | None, command_id: str) -> str:
    if registry is None:
        return command_id
    try:
        return registry.get(command_id).label_zh
    except KeyError:
        return command_id
