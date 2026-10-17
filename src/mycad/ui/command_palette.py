# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Left-panel command palette (UI初次稿 §5): search + category tree.

Data source is the live ``CommandRegistry`` grouped by the id's first
segment (``list_by_category``) — plugins reachable in the registry
surface automatically after ``refresh()``; the §5.3 footer states that
promise verbatim. Reserved extension API (§5.3 ``register_left_item``):
plugins may later attach custom left-panel entries through a method on
this widget; phase 1 ships the comment contract only and no
implementation.

Search matches the command id AND ``label_zh`` (the zh label is the
reason the palette does not reuse ``registry.search`` — that one
deliberately excludes Chinese labels for the English CLI).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mycad.commands.registry import CommandRegistry
from mycad.commands.spec import CommandSpec
from mycad.core.exceptions import UnknownCommandError

#: Footer text from UI draft §5.3, verbatim.
PLUGIN_HINT_TEXT = "插件命令自动出现"

#: Tree data role storing the raw command id on each leaf.
COMMAND_ID_ROLE = Qt.ItemDataRole.UserRole


class CommandPalette(QWidget):
    """Browse/search registered commands and pick one by double-click."""

    #: Emitted with the picked command id (double-click or Enter).
    command_activated = Signal(str)

    def __init__(self, registry: CommandRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._registry = registry

        layout = QVBoxLayout(self)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索命令（id 或中文名）")
        self.search_box.setClearButtonEnabled(True)
        layout.addWidget(self.search_box)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(("命令",))
        layout.addWidget(self.tree)

        self.hint = QLabel(PLUGIN_HINT_TEXT)
        layout.addWidget(self.hint)

        self._fill_from_registry()
        self.search_box.textChanged.connect(self.apply_filter)
        self.tree.itemActivated.connect(self._activate_item)
        self.tree.itemDoubleClicked.connect(self._activate_item)

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def _fill_from_registry(self) -> None:
        """Rebuild the tree from the registry, grouped by id first segment."""
        self.tree.clear()
        for category, specs in self._registry.list_by_category().items():
            group = QTreeWidgetItem((category,))
            for spec in specs:
                child = QTreeWidgetItem((self._leaf_label(spec),))
                child.setData(0, COMMAND_ID_ROLE, spec.id)
                group.addChild(child)
            self.tree.addTopLevelItem(group)

    @staticmethod
    def _leaf_label(spec: CommandSpec) -> str:
        """Readable leaf: the zh label with the raw id in parentheses."""
        return f"{spec.label_zh}（{spec.id}）"

    def refresh(self) -> None:
        """Re-read the registry (a plugin registered since construction
        shows up after this call — the §5.3 promise)."""
        keyword = self.search_box.text()
        self._fill_from_registry()
        self.apply_filter(keyword)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def apply_filter(self, keyword: str) -> int:
        """Filter leaves by id or zh-label substring; returns the hit count.

        With a keyword, non-matching leaves and leaf-less groups hide;
        with an empty keyword everything shows again (a plain refresh).
        """
        needle = keyword.strip().lower()
        hits = 0
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            if group is None:
                continue
            group_hits = 0
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if child is None:
                    continue
                command_id = child.data(0, COMMAND_ID_ROLE) or ""
                matched = (
                    not needle
                    or needle in command_id.lower()
                    or needle in self._zh_label_of(command_id)
                )
                child.setHidden(bool(needle) and not matched)
                if matched:
                    group_hits += 1
                    hits += 1
            group.setHidden(bool(needle) and group_hits == 0)
        return hits

    def _zh_label_of(self, command_id: str) -> str:
        """Label text for the search; unknown ids contribute no zh match."""
        try:
            return self._registry.get(command_id).label_zh
        except UnknownCommandError:
            return ""

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def _activate_item(self, item: QTreeWidgetItem, _column: int) -> None:
        command_id = item.data(0, COMMAND_ID_ROLE)
        if command_id:
            self.command_activated.emit(str(command_id))
