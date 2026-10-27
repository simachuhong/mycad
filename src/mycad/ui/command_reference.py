# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""命令速查对话框：CLI 动词 ↔ 命令 ID ↔ 参数 的可查清单。

新手最容易踩的坑是把命令 ID（``feature.box``）当成 CLI 动词敲进去 ——
CLI 只认短动词（``box``）。本模块把注册表里的每条命令摊平成一张表：
动词、命令 ID、中文名、英文说明、参数（必填带 ``*``，嵌套对象列出子键）。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mycad.commands.grammar import describe_params
from mycad.commands.registry import CommandRegistry
from mycad.ui.cad_icons import set_button_icon

__all__ = ["CommandReferenceDialog", "CommandRow", "collect_rows"]

_COLUMNS = ("动词", "命令 ID", "名称", "说明", "参数")

_HINT = (
    "CLI 只认动词（如 box），不是命令 ID（如 feature.box）；"
    "嵌套参数用点号展开，如 target_face.surface=plane target_face.axis=+Z；"
    "完整示例见 examples/flange_script.txt。"
)


@dataclass(frozen=True)
class CommandRow:
    """One row of the reference table."""

    verb: str
    command_id: str
    label_zh: str
    summary_en: str
    params: str


def collect_rows(registry: CommandRegistry) -> tuple[CommandRow, ...]:
    """Flatten the registry into reference rows, sorted by CLI verb."""
    specs = [spec for group in registry.list_by_category().values() for spec in group]
    rows: list[CommandRow] = []
    for spec in sorted(specs, key=lambda item: (item.cli.verb_aliases or (item.id,))[0]):
        params: list[str] = []
        for doc in describe_params(spec, registry.schema_defs):
            text = f"{doc.key}*" if doc.required else doc.key
            if doc.children:
                text += "(" + ", ".join(doc.children) + ")"
            params.append(text)
        verb = spec.cli.verb_aliases[0] if spec.cli.verb_aliases else spec.id
        rows.append(
            CommandRow(
                verb=verb,
                command_id=spec.id,
                label_zh=spec.label_zh,
                summary_en=spec.summary_en,
                params=", ".join(params),
            )
        )
    return tuple(rows)


class CommandReferenceDialog(QDialog):
    """Modal lookup table over every registered command."""

    def __init__(self, registry: CommandRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("命令速查")
        self.resize(900, 420)
        self._rows = collect_rows(registry)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("命令速查：CLI 动词 ↔ 命令 ID ↔ 参数", self))

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("搜索动词 / 命令 ID / 名称 / 说明")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        self.table = QTableWidget(0, len(_COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(3, 240)
        layout.addWidget(self.table)

        layout.addWidget(QLabel(_HINT, self))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        set_button_icon(buttons.button(QDialogButtonBox.StandardButton.Close), "cancel")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.search.textChanged.connect(self._apply_filter)
        self._apply_filter("")

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        visible = [
            row
            for row in self._rows
            if not needle
            or needle in row.verb.lower()
            or needle in row.command_id.lower()
            or needle in row.label_zh.lower()
            or needle in row.summary_en.lower()
        ]
        self.table.setRowCount(len(visible))
        for index, row in enumerate(visible):
            values = (row.verb, row.command_id, row.label_zh, row.summary_en, row.params)
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(value))
