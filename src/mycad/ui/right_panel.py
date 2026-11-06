# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Right dock five fixed tabs: structure / properties / options / display / measure.

- 「结构」树：文档根节点（part_name，文件名 stem 落 tooltip——F-TREE-01）→
  基准/草图/特征/实体 四分组；数据源 = ``Document.commands``，草图命令位于
  草图组，其他历史命令位于特征组，``named_groups`` 位于实体组；空组显示占位文案。
  历史叶点击发 ``structure_selection_changed(ord)``
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
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast, override

from PySide6.QtCore import (
    QItemSelectionModel,
    QModelIndex,
    QSignalBlocker,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mycad.commands.registry import CommandRegistry
from mycad.commands.spec import CommandSpec
from mycad.core.document import METADATA_KEYS, Document, ExecutedCommand, PlannedCommand
from mycad.core.exceptions import ValidationError
from mycad.core.identity import BodyId
from mycad.core.measurements import (
    MeasurementKernel,
    MeasurementKind,
    MeasurementReference,
    MeasurementRequest,
)
from mycad.core.persistence import LoadedDocument
from mycad.core.semantic_refs import SemanticEdgeRef, SemanticFaceRef
from mycad.core.spatial_references import SpatialReference
from mycad.core.viewport_protocol import BodyResultReference, ViewportBodyOrigin, ViewportData
from mycad.ui.cad_icons import (
    STRUCTURE_ICONS,
    command_icon_name,
    current_icon_theme,
    refresh_tree_icons,
    set_button_icon,
    set_tree_icon,
)
from mycad.ui.parameter_forms import ParameterForm
from mycad.ui.plan_draft import PlanDraftController
from mycad.ui.theme import ThemeName
from mycad.ui.viewport import SelectionState


class _HistoryImpactLabel(QLabel):
    @override
    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self.setToolTip(text)


class HistoryEditDialog(QDialog):
    """Typed parameter editor with a normalized delta and replay preview."""

    candidate_preview_requested = Signal(object, str)
    candidate_discard_requested = Signal(object)

    def __init__(
        self,
        spec: CommandSpec,
        params: Mapping[str, object],
        registry: CommandRegistry,
        *,
        ordinal: int,
        downstream: Sequence[ExecutedCommand],
        parent: QWidget | None = None,
        candidate_preview: bool = False,
        embedded: bool = False,
        can_cancel: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑草图" if spec.id == "sketch.create" else "编辑历史特征")
        self._ordinal = ordinal
        self._baseline = dict(params)
        self._downstream = tuple(downstream)
        self._preview_params: dict[str, object] | None = None
        self._candidate_preview = candidate_preview
        self._can_cancel = can_cancel
        self.cancel_requested = False
        self._dialog_closed = False
        self._cancel_retry_timer = QTimer(self)
        self._cancel_retry_timer.setSingleShot(True)
        self._cancel_retry_timer.timeout.connect(self.reject)
        self.finished.connect(self._mark_closed)
        self._preview_reason = ""
        self.candidate: object | None = None
        self.repair_mode = False
        self.result_params: dict[str, object] = {}
        self.edit_reason = ""
        self.parameter_form = ParameterForm(spec, params, registry, self)
        self.impact_label = _HistoryImpactLabel("修改参数后预览影响，再明确确认重建。", self)
        self.impact_label.setObjectName("historyEditImpact")
        self.impact_label.setWordWrap(True)
        self.reason_field = QLineEdit(self)
        self.reason_field.setObjectName("historyEditReason")
        self.reason_field.setPlaceholderText("填写本次修改原因")
        self.preview_button = QPushButton("预览影响", self)
        self.preview_button.setObjectName("previewHistoryEdit")
        self.confirm_button = QPushButton("确认并重建", self)
        self.confirm_button.setObjectName("confirmHistoryEdit")
        self.confirm_button.setEnabled(False)
        self.repair_button = QPushButton("重选失效面…", self)
        self.repair_button.setVisible(False)
        self.repair_button.setEnabled(False)
        self.cancel_button = QPushButton("取消", self)
        self.parameter_button = QPushButton("参数…", self)
        self.parameter_dialog = QDialog(self)
        self.parameter_dialog.setWindowTitle("编辑历史参数")
        self.preview_button.clicked.connect(self.preview_changes)
        self.confirm_button.clicked.connect(self.confirm_changes)
        self.repair_button.clicked.connect(self.begin_repair)
        self.cancel_button.clicked.connect(self.reject)
        self.parameter_form.values_changed.connect(self._invalidate_candidate)
        self.reason_field.textChanged.connect(self._invalidate_candidate)
        if embedded:
            self.reason_field.setMaximumWidth(240)
            self.impact_label.setMinimumWidth(240)
            parameter_layout = QVBoxLayout(self.parameter_dialog)
            scroll = QScrollArea(self.parameter_dialog)
            scroll.setWidgetResizable(True)
            scroll.setWidget(self.parameter_form)
            parameter_layout.addWidget(scroll)
            done = QPushButton("完成", self.parameter_dialog)
            done.clicked.connect(self.parameter_dialog.accept)
            parameter_layout.addWidget(done)
            self.parameter_dialog.resize(480, 320)
            self.parameter_button.clicked.connect(self.parameter_dialog.exec)
            layout = QHBoxLayout(self)
            layout.addWidget(self.parameter_button)
            layout.addWidget(QLabel("修改原因", self))
            layout.addWidget(self.reason_field)
            layout.addWidget(self.impact_label)
            layout.addWidget(self.preview_button)
            layout.addWidget(self.repair_button)
            layout.addWidget(self.confirm_button)
            layout.addWidget(self.cancel_button)
            layout.addStretch(1)
        else:
            self.parameter_button.hide()
            layout = QVBoxLayout(self)
            layout.addWidget(self.parameter_form)
            layout.addWidget(self.impact_label)
            layout.addWidget(QLabel("修改原因", self))
            layout.addWidget(self.reason_field)
            layout.addWidget(self.preview_button)
            layout.addWidget(self.confirm_button)
            layout.addWidget(self.repair_button)
            layout.addWidget(self.cancel_button)

    def set_cancel_guard(self, guard: Callable[[], bool]) -> None:
        self._can_cancel = guard

    def _execution_ready(self) -> bool:
        if self._dialog_closed:
            return False
        if not self.cancel_requested and (self._can_cancel is None or self._can_cancel()):
            return True
        self.impact_label.setText("请等待当前操作完成后再处理历史候选。")
        return False

    @override
    def accept(self) -> None:
        if self._execution_ready():
            super().accept()

    def _mark_closed(self, _result: int) -> None:
        self._dialog_closed = True
        self._cancel_retry_timer.stop()

    @override
    def reject(self) -> None:
        if self._dialog_closed:
            return
        if self._can_cancel is not None and not self._can_cancel():
            self.cancel_requested = True
            self.impact_label.setText("正在结束候选预览，完成后取消。")
            self._cancel_retry_timer.start(100)
            return
        self.cancel_requested = False
        self._cancel_retry_timer.stop()
        super().reject()

    def _invalidate_candidate(self) -> None:
        if self._dialog_closed or not self._candidate_preview or self._preview_params is None:
            return
        if self.candidate is not None:
            self.candidate_discard_requested.emit(self.candidate)
            self.candidate = None
        self._preview_params = None
        self.confirm_button.setEnabled(False)
        self.repair_button.setEnabled(False)
        self.repair_button.setVisible(False)
        self.impact_label.setText("参数或原因已变化，请重新预览候选。")

    def preview_changes(self) -> None:
        """Validate and show the exact normalized delta before confirmation."""

        if not self._execution_ready():
            return

        if self._candidate_preview and self.candidate is not None:
            self.candidate_discard_requested.emit(self.candidate)
            self.candidate = None
        self.repair_button.setEnabled(False)
        self.repair_button.setVisible(False)

        try:
            normalized = self.parameter_form.normalized_params()
        except ValidationError as exc:
            self._preview_params = None
            self.confirm_button.setEnabled(False)
            self.impact_label.setText(f"参数无效：{exc}")
            return
        delta = {
            key: {"from": self._baseline.get(key), "to": normalized.get(key)}
            for key in sorted(set(self._baseline) | set(normalized))
            if self._baseline.get(key) != normalized.get(key)
        }
        if not delta:
            self._preview_params = None
            self.confirm_button.setEnabled(False)
            self.impact_label.setText("没有变化；请修改至少一个参数。")
            return
        self._preview_params = normalized
        downstream_ids = ", ".join(command.id for command in self._downstream) or "无"
        self.impact_label.setText(
            f"修改 #{self._ordinal}；将重建该特征及 {len(self._downstream)} 条下游命令"
            f"（{downstream_ids}）。规范化参数差异："
            f"{json.dumps(delta, ensure_ascii=False, sort_keys=True)}"
        )
        if self._candidate_preview:
            reason = self.reason_field.text().strip()
            self.confirm_button.setEnabled(False)
            if not reason:
                self.impact_label.setText("请填写修改原因，再预览候选。")
                return
            self._preview_reason = reason
            self.impact_label.setText(self.impact_label.text() + " 正在重放候选…")
            self.candidate_preview_requested.emit(normalized, reason)
            return
        self.confirm_button.setEnabled(True)

    def candidate_preview_finished(
        self, candidate: object | None, message: str, *, repairable: bool = False
    ) -> bool:
        """Accept a result only while the exact submitted inputs are still present."""
        if self._dialog_closed or self.cancel_requested:
            return False
        try:
            current = self.parameter_form.normalized_params()
        except ValidationError:
            current = None
        if (
            current != self._preview_params
            or self.reason_field.text().strip() != self._preview_reason
        ):
            self.confirm_button.setEnabled(False)
            self.impact_label.setText("参数或原因已变化，请重新预览候选。")
            return False
        self.candidate = candidate
        self.impact_label.setText(self.impact_label.text() + " " + message)
        self.confirm_button.setEnabled(candidate is not None and not repairable)
        self.repair_button.setVisible(candidate is not None and repairable)
        self.repair_button.setEnabled(candidate is not None and repairable)
        return candidate is not None

    def begin_repair(self) -> None:
        """Transfer the failed candidate only after an explicit repair request."""
        if not self._execution_ready():
            return
        if self.candidate is None or self._preview_params is None:
            return
        try:
            current = self.parameter_form.normalized_params()
        except ValidationError:
            self._invalidate_candidate()
            return
        if (
            current != self._preview_params
            or self.reason_field.text().strip() != self._preview_reason
        ):
            self._invalidate_candidate()
            return
        self.result_params = current
        self.edit_reason = self._preview_reason
        self.repair_mode = True
        self.accept()

    def confirm_changes(self) -> None:
        """Accept only the same non-no-op proposal the user previewed."""

        if not self._execution_ready():
            return

        if self._preview_params is None:
            self.preview_changes()
            return
        try:
            normalized = self.parameter_form.normalized_params()
        except ValidationError as exc:
            self.preview_changes()
            self.impact_label.setText(f"参数无效：{exc}")
            return
        if normalized != self._preview_params:
            self.preview_changes()
            return
        reason = self.reason_field.text().strip()
        if not reason:
            self.impact_label.setText("请填写修改原因，再确认重建。")
            return
        if self._candidate_preview and (self.candidate is None or reason != self._preview_reason):
            self.impact_label.setText("参数或原因已变化，请重新预览候选。")
            self.confirm_button.setEnabled(False)
            return
        self.result_params = normalized
        self.edit_reason = reason
        self.accept()


#: 五固定页顺序即 addTab 顺序（测试钉住）。
RIGHT_TAB_TITLES: tuple[str, ...] = ("结构", "属性", "选项", "显示", "测量")

#: 结构树四分组（初稿 §6；基准/草图阶段 1 恒为占位）。
STRUCTURE_GROUP_TITLES: tuple[str, ...] = ("基准", "草图", "特征", "实体")
SKETCH_GROUP_TITLE: str = "草图"
FEATURE_GROUP_TITLE: str = "特征"
SOLIDS_GROUP_TITLE: str = "实体"
EMPTY_PROMPT: str = "（空）"
UNTITLED_DOCUMENT: str = "未命名文档"

#: 结构叶子的角色槽：UserRole 存 feature_history ordinal。
ORDINAL_ROLE: int = int(Qt.ItemDataRole.UserRole)
BODY_ROLE: int = ORDINAL_ROLE + 2
DATUM_ROLE: int = ORDINAL_ROLE + 3


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
    body_selection_requested = Signal(object)
    datum_selection_requested = Signal(object)
    datum_visibility_requested = Signal(object, bool)
    body_visibility_requested = Signal(object, bool)
    show_all_bodies_requested = Signal()
    options_error = Signal(str)
    history_edit_requested = Signal(int, object, str, str)
    history_candidate_preview_requested = Signal(object, int, object, str)
    history_candidate_commit_requested = Signal(object, int)
    history_candidate_discard_requested = Signal(object)
    history_candidate_repair_requested = Signal(object, int, object, str)
    history_candidate_open_requested = Signal(object, int)
    part_sketch_edit_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_theme: ThemeName = current_icon_theme()
        self._registry: CommandRegistry | None = None
        self._document: Document | None = None
        self._loaded: LoadedDocument | None = None
        self._selected_ordinal: int | None = None
        self._body_ids: tuple[BodyId, ...] = ()
        self._body_origins: dict[BodyId, ViewportBodyOrigin] = {}
        self._origin_commands: dict[str, ExecutedCommand] = {}
        self._hidden_body_ids: frozenset[BodyId] = frozenset()
        self._hidden_datums: set[SpatialReference] = set()
        self._body_visibility_editable = True
        self._draft: PlanDraftController | None = None
        self._document_name: str | None = None
        self._options_key_by_row: list[str] = []
        self._filling_options = False

        self._tabs = QTabWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)

        self._structure_tree = QTreeWidget()
        self._structure_tree.setHeaderLabels(("结构", "显隐"))
        self._structure_tree.header().setStretchLastSection(False)
        self._structure_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._structure_tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._structure_tree.setIconSize(QSize(20, 20))
        self._structure_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._structure_tree.itemClicked.connect(self._on_structure_item_clicked)
        self._structure_tree.itemChanged.connect(self._on_body_visibility_changed)
        self._view_selection_label = QLabel("视口选择：无")
        self._view_selection_label.setObjectName("viewSelectionIdentity")
        self._view_selection_label.setWordWrap(True)
        self._structure_tab = QWidget(self)
        structure_layout = QVBoxLayout(self._structure_tab)
        structure_layout.addWidget(self._view_selection_label)
        self._body_display_label = QLabel("勾选实体控制显示；隐藏不影响建模和导出。")
        self._body_display_label.setWordWrap(True)
        self._show_all_bodies_button = QPushButton("显示全部实体")
        self._show_all_bodies_button.setObjectName("showAllBodies")
        self._show_all_bodies_button.clicked.connect(self.show_all_bodies_requested.emit)
        structure_layout.addWidget(self._body_display_label)
        structure_layout.addWidget(self._show_all_bodies_button)
        structure_layout.addWidget(self._structure_tree)

        self._property_table = QTableWidget(0, 3)
        self._property_table.setHorizontalHeaderLabels(("参数", "类型", "当前值"))
        # 只读（计划 todo 7："属性表不做编辑"）。
        self._property_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._property_table.horizontalHeader().setStretchLastSection(True)
        self._property_table.verticalHeader().setVisible(False)
        self._property_tab = QWidget(self)
        property_layout = QVBoxLayout(self._property_tab)
        property_layout.setContentsMargins(0, 0, 0, 0)
        property_layout.addWidget(self._property_table)
        self._edit_history_button = QPushButton("编辑选中特征…", self._property_tab)
        self._edit_history_button.setObjectName("editHistoryFeature")
        set_button_icon(self._edit_history_button, "modify")
        self._edit_history_button.setVisible(False)
        self._edit_history_button.clicked.connect(self._on_edit_history_clicked)
        property_layout.addWidget(self._edit_history_button)
        self._part_sketch_button = QPushButton("原位编辑草图…", self._property_tab)
        self._part_sketch_button.setObjectName("editPartSketch")
        self._part_sketch_button.setVisible(False)
        self._part_sketch_button.clicked.connect(self._on_part_sketch_edit_clicked)
        property_layout.addWidget(self._part_sketch_button)
        self._options_table = QTableWidget(0, 2)
        self._options_table.setHorizontalHeaderLabels(("参数", "当前值"))
        self._options_table.horizontalHeader().setStretchLastSection(True)
        self._options_table.verticalHeader().setVisible(False)
        self._options_table.itemChanged.connect(self._on_options_item_changed)

        self._tabs.addTab(self._structure_tab, RIGHT_TAB_TITLES[0])
        self._tabs.addTab(self._property_tab, RIGHT_TAB_TITLES[1])
        self._tabs.addTab(self._options_table, RIGHT_TAB_TITLES[2])
        self._display_tab = self._placeholder_tab("显示控制占用位（后续阶段）")
        self._measurement_kernel: MeasurementKernel | None = None
        self._measurement_references: tuple[MeasurementReference, ...] = ()
        self._measurement_kind: MeasurementKind = "body_volume"
        self._measurement_result: QLabel | None = None
        self._measure_button: QPushButton | None = None
        self._measurement_target_combos: tuple[QComboBox, QComboBox] | None = None
        self._measurement_busy = False
        self._measure_tab = self._build_measurement_tab()
        self._tabs.addTab(self._display_tab, RIGHT_TAB_TITLES[3])
        self._tabs.addTab(self._measure_tab, RIGHT_TAB_TITLES[4])
        self._tabs.setTabEnabled(self._tabs.indexOf(self._display_tab), False)
        self._tabs.setTabEnabled(self._tabs.indexOf(self._measure_tab), False)

        self._show_document_properties()

    # ------------------------------------------------------------------ API

    @property
    def tabs(self) -> QTabWidget:
        """只读访问五页容器（占位页禁用态的断言由此发出）。"""
        return self._tabs

    def take_structure_tab(self) -> QWidget:
        """Move the existing structure page into a navigation container."""
        index = self._tabs.indexOf(self._structure_tab)
        if index >= 0:
            self._tabs.removeTab(index)
        return self._structure_tab

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

    @property
    def view_selection_label(self) -> QLabel:
        """Status label showing the runtime identity selected in the viewport."""
        return self._view_selection_label

    def set_view_selection(self, selection: SelectionState | None) -> None:
        """Synchronize runtime topology identity without selecting history rows."""
        if selection is None:
            self._view_selection_label.setText("视口选择：无")
            self._view_selection_label.setToolTip("")
            current = self._structure_tree.currentItem()
            if current is not None and isinstance(current.data(0, BODY_ROLE), BodyId):
                self._structure_tree.clearSelection()
                self._structure_tree.setCurrentIndex(QModelIndex())
            return
        self._structure_tree.clearSelection()
        self._structure_tree.setCurrentIndex(QModelIndex())
        kind_labels = {"body": "实体", "face": "面", "edge": "边", "vertex": "顶点"}
        body_labels = ", ".join(str(identity.value)[:8] for identity in selection.body_ids)
        topology_labels = ", ".join(str(identity.value)[:8] for identity in selection.topology_ids)
        suffix = "" if not topology_labels else f" · 拓扑 {topology_labels}"
        self._view_selection_label.setToolTip(
            f"视口选择：{kind_labels[selection.kind]} · 实体 {body_labels}{suffix}"
        )
        for item in self._structure_tree.findItems(
            "", Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive
        ):
            if item.data(0, BODY_ROLE) in selection.body_ids:
                self._structure_tree.setCurrentItem(
                    item, 0, QItemSelectionModel.SelectionFlag.NoUpdate
                )
                item.setSelected(True)
        count = len(selection.body_ids) if selection.kind == "body" else len(selection.topology_ids)
        owners = "、".join(
            f"实体 {self._body_ids.index(identity) + 1}"
            for identity in dict.fromkeys(selection.body_ids)
            if identity in self._body_ids
        )
        self._view_selection_label.setText(
            f"视口选择：{kind_labels[selection.kind]} {count} · {owners}"
        )
        self._fill_property_table(
            [
                ("对象类型", "", kind_labels[selection.kind]),
                ("选中数量", "", str(count)),
                ("所属实体", "", owners),
                *[
                    (f"{self.body_name(identity)} · {label}", "", text)
                    for identity in dict.fromkeys(selection.body_ids)
                    for label, text, _ordinal in self._origin_rows(identity)
                ],
            ]
        )

    def body_name(self, identity: BodyId) -> str:
        return (
            f"实体 {self._body_ids.index(identity) + 1}"
            if identity in self._body_ids
            else "已过期实体"
        )

    def set_body_display(self, hidden: Sequence[BodyId], *, editable: bool, hint: str) -> None:
        self._hidden_body_ids = frozenset(hidden)
        self._body_visibility_editable = editable
        self._show_all_bodies_button.setEnabled(editable and bool(hidden))
        self._body_display_label.setText(hint)
        blocker = QSignalBlocker(self._structure_tree)
        for item in self._structure_tree.findItems(
            "", Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive
        ):
            identity = item.data(0, BODY_ROLE)
            if isinstance(identity, BodyId):
                self._configure_body_visibility(item, identity)
        del blocker

    def set_datum_visibility(self, hidden: Sequence[SpatialReference]) -> None:
        self._hidden_datums = set(hidden)
        blocker = QSignalBlocker(self._structure_tree)
        for item in self._structure_tree.findItems(
            "", Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive
        ):
            reference = item.data(0, DATUM_ROLE)
            if isinstance(reference, SpatialReference):
                visible = reference not in self._hidden_datums
                item.setCheckState(0, Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked)
                item.setText(1, "显示" if visible else "隐藏")
        del blocker

    def _configure_body_visibility(self, item: QTreeWidgetItem, identity: BodyId) -> None:
        flags = item.flags()
        if self._body_visibility_editable:
            item.setFlags(flags | Qt.ItemFlag.ItemIsUserCheckable)
        else:
            item.setFlags(flags & ~Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            0,
            Qt.CheckState.Unchecked if identity in self._hidden_body_ids else Qt.CheckState.Checked,
        )

        item.setText(1, "隐藏" if identity in self._hidden_body_ids else "显示")

    def _on_body_visibility_changed(self, item: QTreeWidgetItem, column: int) -> None:
        datum = item.data(0, DATUM_ROLE)
        if column == 0 and isinstance(datum, SpatialReference):
            visible = item.checkState(0) == Qt.CheckState.Checked
            if visible:
                self._hidden_datums.discard(datum)
            else:
                self._hidden_datums.add(datum)
            item.setText(1, "显示" if visible else "隐藏")
            self.datum_visibility_requested.emit(datum, visible)
            return
        identity = item.data(0, BODY_ROLE)
        if column == 0 and isinstance(identity, BodyId) and self._body_visibility_editable:
            self.body_visibility_requested.emit(
                identity, item.checkState(0) == Qt.CheckState.Checked
            )

    def _origin_rows(self, identity: BodyId) -> list[tuple[str, str, int | None]]:
        origin = self._body_origins.get(identity)
        if origin is None:
            return [("来源", "来源记录不可用", None)]
        role_names = {
            "target": "目标",
            "tool": "刀具",
            "source": "源实体",
            "seed": "种子",
            "model": "步骤输入",
        }
        return [
            ("来源", *self._origin_label(origin.result)),
            *[(role_names[item.role], *self._origin_label(item.result)) for item in origin.inputs],
        ]

    def _origin_label(self, result: BodyResultReference) -> tuple[str, int | None]:
        command = self._origin_commands.get(result.state_id)
        if command is None:
            return ("历史步骤映射不可用", None)
        return (
            f"#{command.ordinal} {_readable_name(self._registry, command.id)} · 结果 {result.solid_index + 1}",
            command.ordinal,
        )

    def set_current_snapshot(self, snapshot: object, *, state_ids: Sequence[str] = ()) -> None:
        """Populate actual solids from the current render DTO, never history order."""
        self._body_ids = (
            tuple(dict.fromkeys(snapshot.triangle_body_ids))
            if isinstance(snapshot, ViewportData)
            else ()
        )
        self._body_origins = (
            {origin.body_id: origin for origin in snapshot.body_origins}
            if isinstance(snapshot, ViewportData)
            else {}
        )
        commands = () if self._document is None else self._document.commands
        self._origin_commands = (
            dict(zip(state_ids, commands, strict=True))
            if len(state_ids) == len(commands) and len(set(state_ids)) == len(state_ids)
            else {}
        )
        self.refresh_structure()

    def bind_document(
        self,
        loaded: LoadedDocument,
        registry: CommandRegistry,
        *,
        document_stem: str | None = None,
        kernel: MeasurementKernel | None = None,
    ) -> None:
        """绑定单文档视图（结构树 + 文档级属性）。

        ``document_stem`` 由窗口层在打开文档时传入（LoadedDocument 不携带
        路径）；未传则以 "未命名文档" 作根。
        """
        self._registry = registry
        self._loaded = loaded
        self._document = loaded.document
        self._hidden_datums.clear()
        self._selected_ordinal = None
        self._body_ids = ()
        self._body_origins = {}
        self._origin_commands = {}
        self.set_view_selection(None)
        self._edit_history_button.setVisible(False)
        self._part_sketch_button.setVisible(False)
        self._document_name = document_stem
        self._measurement_kernel = kernel
        self._measurement_references = ()
        self._tabs.setTabEnabled(self._tabs.indexOf(self._measure_tab), kernel is not None)
        if self._measurement_result is not None:
            self._measurement_result.setText("选择测量类型并执行；结果来自当前精确 BREP。")
        self._refresh_measurement_targets()
        self.refresh_structure()
        self._show_document_properties()

    def set_measurement_references(self, references: Sequence[MeasurementReference]) -> None:
        """Provide exact, revision-bound face or edge references for a query."""

        self._measurement_references = tuple(references)

    def set_measurement_busy(self, busy: bool) -> None:
        """Keep measurement queries off the GUI thread during serialized CAD work."""

        self._measurement_busy = busy
        self._measurement_kind_combo.setEnabled(not busy)
        if self._measure_button is not None:
            self._measure_button.setEnabled(not busy)
        if self._measurement_target_combos is not None:
            for combo in self._measurement_target_combos:
                combo.setEnabled(not busy)
        if not busy:
            self._refresh_measurement_targets()

    def invalidate_measurement(self) -> None:
        """Clear a displayed value after the active geometry revision changes."""

        if self._measurement_result is not None:
            self._measurement_result.setText("模型已变化，请重新测量。")
        self._measurement_references = ()
        self._refresh_measurement_targets()

    def _build_measurement_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._measurement_kind_combo = QComboBox(tab)
        self._measurement_kind_combo.setObjectName("measurementKind")
        choices: tuple[tuple[str, MeasurementKind], ...] = (
            ("当前实体体积", "body_volume"),
            ("圆柱面直径", "cylindrical_face_diameter"),
            ("圆边中心距", "circular_edge_center_distance"),
            ("平行平面间距", "parallel_plane_separation"),
        )
        for label, kind in choices:
            self._measurement_kind_combo.addItem(label, kind)
        self._measurement_kind_combo.currentIndexChanged.connect(self._on_measurement_kind_changed)
        first_target = QComboBox(tab)
        first_target.setObjectName("measurementTarget0")
        second_target = QComboBox(tab)
        second_target.setObjectName("measurementTarget1")
        self._measurement_target_combos = (first_target, second_target)
        self._measure_button = QPushButton("测量", tab)
        self._measure_button.setObjectName("measureButton")
        self._measure_button.clicked.connect(self._run_measurement)
        self._measurement_result = QLabel("请先绑定当前文档。", tab)
        self._measurement_result.setObjectName("measurementResult")
        self._measurement_result.setWordWrap(True)
        layout.addWidget(self._measurement_kind_combo)
        layout.addWidget(first_target)
        layout.addWidget(second_target)
        layout.addWidget(self._measure_button)
        layout.addWidget(self._measurement_result)
        layout.addStretch(1)
        return tab

    def _on_measurement_kind_changed(self, index: int) -> None:
        raw_kind = self._measurement_kind_combo.itemData(index)
        if raw_kind in (
            "body_volume",
            "cylindrical_face_diameter",
            "circular_edge_center_distance",
            "parallel_plane_separation",
        ):
            self._measurement_kind = raw_kind
        self._measurement_references = ()
        if self._measurement_result is not None:
            self._measurement_result.setText("已清除旧引用；请从当前几何重新选择所需面或边。")
        self._refresh_measurement_targets()

    def _refresh_measurement_targets(self) -> None:
        kernel = self._measurement_kernel
        combos = self._measurement_target_combos
        if combos is None:
            return
        required = {
            "body_volume": 0,
            "cylindrical_face_diameter": 1,
            "circular_edge_center_distance": 2,
            "parallel_plane_separation": 2,
        }[self._measurement_kind]
        if self._measurement_busy:
            for position, combo in enumerate(combos):
                combo.clear()
                combo.setVisible(kernel is not None and position < required)
                combo.setEnabled(False)
            return
        targets = (
            ()
            if kernel is None or required == 0
            else kernel.measurement_targets(self._measurement_kind)
        )
        for position, combo in enumerate(combos):
            combo.clear()
            if position < required:
                prompts = {
                    "cylindrical_face_diameter": "选择一个圆柱面…",
                    "circular_edge_center_distance": "选择圆边…",
                    "parallel_plane_separation": "选择一个平面…",
                }
                combo.addItem(prompts[self._measurement_kind], None)
                for target in targets:
                    combo.addItem(target.label, target.reference)
                combo.setVisible(kernel is not None)
                combo.setEnabled(bool(targets) and not self._measurement_busy)
            else:
                combo.setVisible(False)

    def _selected_measurement_references(self) -> tuple[MeasurementReference, ...]:
        if self._measurement_references:
            return self._measurement_references
        combos = self._measurement_target_combos
        if combos is None:
            return ()
        required = {
            "body_volume": 0,
            "cylindrical_face_diameter": 1,
            "circular_edge_center_distance": 2,
            "parallel_plane_separation": 2,
        }[self._measurement_kind]
        selected: list[MeasurementReference] = []
        for combo in combos[:required]:
            reference = combo.currentData()
            if isinstance(reference, SemanticFaceRef | SemanticEdgeRef):
                selected.append(reference)
        return tuple(selected)

    def _run_measurement(self) -> None:
        kernel = self._measurement_kernel
        label = self._measurement_result
        if kernel is None or label is None or self._measurement_busy:
            return
        result = kernel.measure(
            MeasurementRequest(
                kind=self._measurement_kind,
                references=self._selected_measurement_references(),
                revision=kernel.geometry_revision,
            )
        )
        if result.revision != kernel.geometry_revision:
            label.setText("测量结果已过期，请重新测量。")
            return
        if result.error is not None or result.value is None:
            label.setText(
                f"{result.description}：不可用。{result.error or ''} 来源：{result.source}。"
            )
            return
        label.setText(
            f"{result.description}：{result.value:.9g} {result.unit}（来源：{result.source}）"
        )

    def bind_draft(self, draft: PlanDraftController) -> None:
        """绑定草稿控制器；选项表随信号自动重填。"""
        self._draft = draft
        draft.params_changed.connect(self._on_draft_params_changed)
        draft.plan_replaced.connect(self._refill_options)
        self._refill_options()

    def set_icon_theme(self, theme: ThemeName) -> None:
        self._icon_theme = theme
        refresh_tree_icons(self._structure_tree, theme)

    def refresh_structure(self) -> None:
        """重建结构树（named_group_added/removed 等信号由窗口层转发到这里）。"""
        if self._document is None:
            return
        tree = self._structure_tree
        blocker = QSignalBlocker(tree)
        tree.clear()
        metadata = self._document.metadata
        part_name = metadata.get("part_name")
        label = part_name if isinstance(part_name, str) and part_name else UNTITLED_DOCUMENT
        root = QTreeWidgetItem(tree, [label])
        set_tree_icon(root, "document", self._icon_theme)
        if self._document_name:
            root.setToolTip(0, self._document_name)
        sketch_items: dict[str, QTreeWidgetItem] = {}
        for title in STRUCTURE_GROUP_TITLES:
            group = QTreeWidgetItem(root, [title])
            set_tree_icon(group, STRUCTURE_ICONS[title], self._icon_theme)
            if title == "基准":
                for command in self._document.commands:
                    if command.id not in ("datum.coordinate_system.create", "datum.plane.create"):
                        continue
                    if command.instance_id is None:
                        continue
                    kind = (
                        "coordinate_system"
                        if command.id == "datum.coordinate_system.create"
                        else "datum_plane"
                    )
                    role = "coordinate_system" if kind == "coordinate_system" else "plane"
                    reference = SpatialReference(kind, command.instance_id, role)
                    name = str(command.params.get("name", "基准"))
                    leaf = QTreeWidgetItem(group, [f"{name} · {command.instance_id[:8]}"])
                    leaf.setData(0, DATUM_ROLE, reference)
                    leaf.setData(0, ORDINAL_ROLE, int(command.ordinal))
                    leaf.setFlags(leaf.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    visible = reference not in self._hidden_datums
                    leaf.setCheckState(
                        0, Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked
                    )
                    leaf.setText(1, "显示" if visible else "隐藏")
                    set_tree_icon(leaf, "datum", self._icon_theme)
            elif title == SKETCH_GROUP_TITLE:
                for command in self._document.commands:
                    if command.id == "sketch.create":
                        sketch_id = command.params.get("sketch_id")
                        short_id = sketch_id[:8] if isinstance(sketch_id, str) else "未知身份"
                        leaf = QTreeWidgetItem(group, [f"草图 #{command.ordinal} · {short_id}"])
                        leaf.setData(0, ORDINAL_ROLE, int(command.ordinal))
                        leaf.setToolTip(0, f"草图 #{command.ordinal} · {sketch_id}")
                        set_tree_icon(leaf, "sketch", self._icon_theme)
                        if isinstance(sketch_id, str):
                            sketch_items[sketch_id] = leaf
                    elif command.id.partition(".")[0] == "sketch":
                        sketch_id = command.params.get("sketch_id")
                        parent = sketch_items.get(sketch_id) if isinstance(sketch_id, str) else None
                        label = "草图修订" if command.id == "sketch.revise" else "约束"
                        leaf = QTreeWidgetItem(parent or group, [f"{label} #{command.ordinal}"])
                        leaf.setData(0, ORDINAL_ROLE, int(command.ordinal))
                        leaf.setToolTip(0, f"草图命令 #{command.ordinal} · {command.id}")
                        set_tree_icon(leaf, "features", self._icon_theme)
            elif title == FEATURE_GROUP_TITLE:
                for command in self._document.commands:
                    if command.id.partition(".")[0] in ("sketch", "datum"):
                        continue
                    leaf = QTreeWidgetItem(
                        group,
                        [f"#{command.ordinal} {_readable_name(self._registry, command.id)}"],
                    )
                    leaf.setData(0, ORDINAL_ROLE, int(command.ordinal))
                    leaf.setToolTip(0, f"历史特征 #{command.ordinal} · {command.id}")
                    set_tree_icon(leaf, command_icon_name(command.id), self._icon_theme)
            elif title == SOLIDS_GROUP_TITLE:
                for index, body_id in enumerate(self._body_ids, 1):
                    leaf = QTreeWidgetItem(group, [f"实体 {index}"])
                    leaf.setData(0, BODY_ROLE, body_id)
                    self._configure_body_visibility(leaf, body_id)
                    rows = self._origin_rows(body_id)
                    leaf.setToolTip(0, "\n".join(f"{label}：{text}" for label, text, _ in rows))
                    for label, text, ordinal in rows:
                        link = QTreeWidgetItem(leaf, [f"{label}：{text}"])
                        link.setToolTip(0, "点击预览该历史步骤；输入关系不表示逐面来源。")
                        if ordinal is not None:
                            link.setData(0, ORDINAL_ROLE, ordinal)
                    set_tree_icon(leaf, "box", self._icon_theme)
                for name in self._document.named_groups:
                    leaf = QTreeWidgetItem(group, [name])
                    set_tree_icon(leaf, "group", self._icon_theme)
            if group.childCount() == 0:
                QTreeWidgetItem(group, [EMPTY_PROMPT])
        tree.expandAll()
        del blocker
        if self._selected_ordinal is not None:
            item = self._find_ordinal_item(tree.invisibleRootItem(), self._selected_ordinal)
            if item is not None:
                tree.setCurrentItem(item)
                self._show_properties_for_ordinal(self._selected_ordinal)

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
        datum = item.data(0, DATUM_ROLE)
        if isinstance(datum, SpatialReference):
            self.datum_selection_requested.emit(datum)
            ordinal = item.data(0, ORDINAL_ROLE)
            if isinstance(ordinal, int) and not isinstance(ordinal, bool):
                self._selected_ordinal = ordinal
                self._show_properties_for_ordinal(ordinal)
            return
        body_id = item.data(0, BODY_ROLE)
        if isinstance(body_id, BodyId):
            self.body_selection_requested.emit(body_id)
            return
        ordinal = item.data(0, ORDINAL_ROLE)
        if not isinstance(ordinal, int) or isinstance(ordinal, bool):
            return
        self._selected_ordinal = ordinal
        self.structure_selection_changed.emit(ordinal)
        self._show_properties_for_ordinal(ordinal)

    def select_datum_reference(self, reference: SpatialReference) -> None:
        """Reflect a viewport datum pick without opening history preview."""
        for item in self._structure_tree.findItems(
            "", Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive
        ):
            if item.data(0, DATUM_ROLE) == reference:
                self._structure_tree.setCurrentItem(item)
                self._structure_tree.scrollToItem(item)
                ordinal = item.data(0, ORDINAL_ROLE)
                if isinstance(ordinal, int) and not isinstance(ordinal, bool):
                    self._selected_ordinal = ordinal
                    self._show_properties_for_ordinal(ordinal)
                return

    def _show_properties_for_ordinal(self, ordinal: int) -> None:
        if self._document is None:
            return
        for command in self._document.commands:
            if command.ordinal == ordinal:
                self.show_command_properties(command.id, command.params)
                self._update_history_edit_button(command)
                return

    def select_feature_ordinal(self, ordinal: int | None) -> None:
        """Programmatically select a history row or clear feature selection.

        Current-model picks do not have a feature-source mapping, so they
        clear the history row instead of selecting a guessed ordinal. This
        method does not emit ``structure_selection_changed`` and cannot
        re-enter the tree-to-preview path.
        """
        tree = self._structure_tree
        if ordinal is None:
            # Qt 的 setCurrentItem(None) 会清空选中，但 PySide stub 把参数定
            # 型为非 None；clearSelection 是同一个视觉效果的类型安全写法。
            tree.clearSelection()
            tree.setCurrentIndex(QModelIndex())
            self._selected_ordinal = None
            self._edit_history_button.setVisible(False)
            self._part_sketch_button.setVisible(False)
            self._show_document_properties()
            return
        self._selected_ordinal = ordinal
        item = self._find_ordinal_item(tree.invisibleRootItem(), ordinal)
        if item is not None:
            tree.setCurrentItem(item)
            tree.scrollToItem(item)
        self._show_properties_for_ordinal(ordinal)

    def _update_history_edit_button(self, command: ExecutedCommand) -> None:
        datum_commands = ("datum.coordinate_system.create", "datum.plane.create")
        replayable = (
            command.id.startswith(("feature.", "modify."))
            or command.id == "sketch.create"
            or command.id in datum_commands
        )
        label = "编辑选中草图…" if command.id == "sketch.create" else "编辑选中特征…"
        if command.id in datum_commands:
            label = "编辑选中基准…"
        self._edit_history_button.setText(label)
        self._edit_history_button.setVisible(replayable)
        self._edit_history_button.setEnabled(replayable and self._loaded is not None)
        self._part_sketch_button.setVisible(
            command.id == "sketch.create"
            and self._loaded is not None
            and self._loaded.document.document_type == "part"
        )

    def _on_part_sketch_edit_clicked(self) -> None:
        if self._loaded is None or self._selected_ordinal is None:
            return
        command = next(
            (
                item
                for item in self._loaded.document.commands
                if item.ordinal == self._selected_ordinal
            ),
            None,
        )
        if command is not None and command.id == "sketch.create":
            sketch_id = command.params.get("sketch_id")
            if isinstance(sketch_id, str):
                self.part_sketch_edit_requested.emit(sketch_id)

    def _on_edit_history_clicked(self) -> None:
        loaded = self._loaded
        registry = self._registry
        ordinal = self._selected_ordinal
        if loaded is None or registry is None or ordinal is None:
            return
        commands = loaded.document.commands
        position = next(
            (index for index, command in enumerate(commands) if command.ordinal == ordinal),
            None,
        )
        if position is None:
            return
        command = commands[position]
        if (
            not command.id.startswith(("feature.", "modify."))
            and command.id != "sketch.create"
            and command.id not in ("datum.coordinate_system.create", "datum.plane.create")
        ):
            return
        spec = registry.get(command.id, command.version)
        dialog = HistoryEditDialog(
            spec,
            command.params,
            registry,
            ordinal=ordinal,
            downstream=commands[position + 1 :],
            parent=self,
            candidate_preview=True,
            embedded=True,
        )

        def request_candidate(params: object, reason: str) -> None:
            self.history_candidate_preview_requested.emit(dialog, ordinal, params, reason)

        dialog.candidate_preview_requested.connect(request_candidate)
        dialog.candidate_discard_requested.connect(self.history_candidate_discard_requested.emit)

        def finished(result: int) -> None:
            if result == QDialog.DialogCode.Accepted:
                if dialog.candidate is not None:
                    if dialog.repair_mode:
                        candidate = dialog.candidate
                        params, reason = dialog.result_params, dialog.edit_reason
                        QTimer.singleShot(
                            0,
                            lambda: self.history_candidate_repair_requested.emit(
                                candidate, ordinal, params, reason
                            ),
                        )
                    else:
                        self.history_candidate_commit_requested.emit(dialog.candidate, ordinal)
            elif dialog.candidate is not None:
                self.history_candidate_discard_requested.emit(dialog.candidate)

        dialog.finished.connect(finished)
        self.history_candidate_open_requested.emit(dialog, ordinal)

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
