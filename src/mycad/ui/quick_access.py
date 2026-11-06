# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Per-environment quick access preferences and action configuration."""

from __future__ import annotations

import json
from typing import cast

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from mycad.ui.action_catalog import ActionCatalog

_ENVIRONMENTS = frozenset({"home", "drawing2d", "part", "part-sketch", "drawing", "assembly"})
_PREFIX = "quick-access/v1/"


class QuickAccessStore:
    """Persist ordered action identities without discarding unavailable plugins."""

    def __init__(self, settings: QSettings) -> None:
        self.settings = settings

    @staticmethod
    def _key(environment: str) -> str:
        if environment not in _ENVIRONMENTS:
            raise ValueError(f"Unknown workspace environment: {environment}")
        return _PREFIX + environment

    def load(self, environment: str, default: tuple[str, ...]) -> tuple[str, ...]:
        value = self.settings.value(self._key(environment))
        if not isinstance(value, str):
            return default
        try:
            parsed: object = json.loads(value)
        except (TypeError, ValueError):
            return default
        if not isinstance(parsed, list):
            return default
        items = cast("list[object]", parsed)
        if any(not isinstance(item, str) or not item for item in items):
            return default
        identities = tuple(item for item in items if isinstance(item, str))
        if len(set(identities)) != len(identities):
            return default
        return identities

    def save(self, environment: str, identities: tuple[str, ...]) -> None:
        if any(not item for item in identities):
            raise ValueError("quick access identities must be non-empty strings")
        if len(set(identities)) != len(identities):
            raise ValueError("quick access identities must be unique")
        self.settings.setValue(self._key(environment), json.dumps(identities, ensure_ascii=False))
        self.settings.sync()

    def reset(self, environment: str) -> None:
        self.settings.remove(self._key(environment))
        self.settings.sync()


class QuickAccessController:
    """Place shared actions in a toolbar, retaining disabled missing entries."""

    def __init__(
        self,
        toolbar: QToolBar,
        catalog: ActionCatalog,
        store: QuickAccessStore,
        *,
        defaults: tuple[str, ...],
        before: QAction | None = None,
    ) -> None:
        self.toolbar = toolbar
        self.catalog = catalog
        self.store = store
        self.defaults = defaults
        self.before = before
        self.environment = "home"
        self.identities: tuple[str, ...] = ()
        self._attached: list[QAction] = []
        self._missing: dict[str, QAction] = {}
        self.catalog.changed.connect(self.refresh)

    def set_environment(self, environment: str) -> None:
        self.identities = self.store.load(environment, self.defaults)
        self.environment = environment
        self.refresh()

    def set_actions(self, identities: tuple[str, ...]) -> None:
        self.store.save(self.environment, identities)
        self.identities = identities
        self.refresh()

    def reset(self) -> None:
        self.store.reset(self.environment)
        self.identities = self.defaults
        self.refresh()

    def refresh(self) -> None:
        for action in self._attached:
            self.toolbar.removeAction(action)
        self._attached.clear()
        for identity in self.identities:
            action = self.catalog.find(identity)
            if action is None:
                action = self._missing.get(identity)
                if action is None:
                    action = QAction(f"不可用：{identity}", self.toolbar)
                    action.setToolTip(f"动作 {identity} 当前不可用；对应插件可能未加载。")
                    action.setEnabled(False)
                    self._missing[identity] = action
            if self.before is None:
                self.toolbar.addAction(action)
            else:
                self.toolbar.insertAction(self.before, action)
            self._attached.append(action)


class QuickAccessDialog(QDialog):
    """Edit a temporary ordered action list; the caller saves on acceptance."""

    def __init__(
        self,
        catalog: ActionCatalog,
        identities: tuple[str, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("自定义快速访问")
        self.catalog = catalog
        self.available = QComboBox(self)
        self.selected = QListWidget(self)
        self.add_button = QPushButton("添加", self)
        self.remove_button = QPushButton("移除", self)
        self.up_button = QPushButton("上移", self)
        self.down_button = QPushButton("下移", self)
        confirm = QPushButton("确定", self)
        cancel = QPushButton("取消", self)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("当前环境的快速访问动作", self))
        layout.addWidget(self.selected)
        row = QHBoxLayout()
        for button in (self.remove_button, self.up_button, self.down_button):
            row.addWidget(button)
        layout.addLayout(row)
        add_row = QHBoxLayout()
        add_row.addWidget(self.available, 1)
        add_row.addWidget(self.add_button)
        layout.addLayout(add_row)
        finish = QHBoxLayout()
        finish.addStretch(1)
        finish.addWidget(confirm)
        finish.addWidget(cancel)
        layout.addLayout(finish)
        self.add_button.clicked.connect(self._add)
        self.remove_button.clicked.connect(self._remove)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        confirm.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        for identity in identities:
            self._append(identity)
        self._refresh_available()

    def _append(self, identity: str) -> None:
        action = self.catalog.find(identity)
        label = (
            f"不可用：{identity}"
            if action is None
            else action.text()
            if action.isEnabled()
            else f"{action.text()}（不可用）"
        )
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, identity)
        item.setToolTip(
            f"{identity} · 当前不可用；对应插件可能未加载"
            if action is None
            else f"{identity} · {action.toolTip()}"
        )
        self.selected.addItem(item)

    def identities(self) -> tuple[str, ...]:
        result: list[str] = []
        for index in range(self.selected.count()):
            item = self.selected.item(index)
            value = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(value, str):
                result.append(value)
        return tuple(result)

    def _refresh_available(self) -> None:
        present = set(self.identities())
        self.available.clear()
        for identity, action in self.catalog.entries():
            if identity not in present:
                label = action.text() if action.isEnabled() else f"{action.text()}（不可用）"
                self.available.addItem(label, identity)
                self.available.setItemData(
                    self.available.count() - 1, action.toolTip(), Qt.ItemDataRole.ToolTipRole
                )
        self.add_button.setEnabled(self.available.count() > 0)

    def _add(self) -> None:
        identity = self.available.currentData()
        if isinstance(identity, str) and identity not in self.identities():
            self._append(identity)
            self.selected.setCurrentRow(self.selected.count() - 1)
            self._refresh_available()

    def _remove(self) -> None:
        row = self.selected.currentRow()
        if row >= 0:
            self.selected.takeItem(row)
            self.selected.setCurrentRow(min(row, self.selected.count() - 1))
            self._refresh_available()

    def _move(self, offset: int) -> None:
        row = self.selected.currentRow()
        target = row + offset
        if row < 0 or target < 0 or target >= self.selected.count():
            return
        item = self.selected.takeItem(row)
        self.selected.insertItem(target, item)
        self.selected.setCurrentRow(target)
