# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Versioned UI layout storage with non-destructive legacy migration."""

import json
from typing import cast

from PySide6.QtCore import QByteArray, QSettings

_ENVIRONMENTS = frozenset({"home", "drawing2d", "part", "part-sketch", "drawing", "assembly"})
_PREFIX = "workspace-layout/v1/"
_LOCK_PREFIX = "workspace-layout/v1-lock/"
_CONSOLE_PREFIX = "workspace-layout/v1-console/"
_LEGACY = "mainWindow/state"
_BACKUP = "workspace-layout/legacy/mainWindow-state"
_MIGRATED = "workspace-layout/legacy/migrated-v1"


class WorkspaceLayoutStore:
    def __init__(self, settings: QSettings) -> None:
        self.settings = settings

    @staticmethod
    def _key(environment: str) -> str:
        if environment not in _ENVIRONMENTS:
            raise ValueError(f"Unknown workspace environment: {environment}")
        return _PREFIX + environment

    def load(self, environment: str) -> QByteArray | None:
        value = self.settings.value(self._key(environment))
        return QByteArray(value) if isinstance(value, QByteArray) else None

    def save(self, environment: str, state: QByteArray) -> None:
        self.settings.setValue(self._key(environment), state)
        self.settings.sync()

    def load_locked(self, environment: str) -> bool | None:
        key = _LOCK_PREFIX + self._key(environment).removeprefix(_PREFIX)
        if not self.settings.contains(key):
            return None
        value = self.settings.value(key, type=bool)
        return value if isinstance(value, bool) else None

    def save_locked(self, environment: str, locked: bool) -> None:
        key = _LOCK_PREFIX + self._key(environment).removeprefix(_PREFIX)
        self.settings.setValue(key, locked)
        self.settings.sync()

    def load_console(self, environment: str) -> tuple[bool, int, int]:
        key = _CONSOLE_PREFIX + self._key(environment).removeprefix(_PREFIX)
        value = self.settings.value(key)
        if not isinstance(value, str):
            return False, 0, 240
        try:
            parsed: object = json.loads(value)
        except (TypeError, ValueError):
            return False, 0, 240
        if not isinstance(parsed, list):
            return False, 0, 240
        items = cast("list[object]", parsed)
        if (
            len(items) != 3
            or not isinstance(items[0], bool)
            or type(items[1]) is not int
            or type(items[2]) is not int
        ):
            return False, 0, 240
        expanded, page, height = items
        if (
            not isinstance(expanded, bool)
            or not isinstance(page, int)
            or not isinstance(height, int)
        ):
            return False, 0, 240
        if not 0 <= page < 4 or not 160 <= height <= 2000:
            return False, 0, 240
        return expanded, page, height

    def has_console(self, environment: str) -> bool:
        key = _CONSOLE_PREFIX + self._key(environment).removeprefix(_PREFIX)
        return self.settings.contains(key)

    def save_console(self, environment: str, expanded: bool, page: int, height: int) -> None:
        key = _CONSOLE_PREFIX + self._key(environment).removeprefix(_PREFIX)
        if not 0 <= page < 4 or not 160 <= height <= 2000:
            raise ValueError("invalid console page or height")
        self.settings.setValue(key, json.dumps((expanded, page, height)))
        self.settings.sync()

    def reset_console(self, environment: str) -> None:
        key = _CONSOLE_PREFIX + self._key(environment).removeprefix(_PREFIX)
        self.settings.remove(key)
        self.settings.sync()

    def reset(self, environment: str) -> None:
        key = self._key(environment)
        self.settings.remove(key)
        self.settings.remove(_LOCK_PREFIX + key.removeprefix(_PREFIX))
        self.settings.remove(_CONSOLE_PREFIX + key.removeprefix(_PREFIX))
        self.settings.sync()

    def migrate_legacy(self) -> None:
        if self.settings.contains(_MIGRATED):
            return
        if self.settings.contains(_LEGACY):
            value = self.settings.value(_LEGACY)
            if not self.settings.contains(_BACKUP):
                self.settings.setValue(_BACKUP, value)
            if isinstance(value, QByteArray) and not self.settings.contains(self._key("part")):
                self.settings.setValue(self._key("part"), value)
        legacy_lock = "toolbar/locked"
        lock_key = _LOCK_PREFIX + "part"
        if self.settings.contains(legacy_lock):
            if not self.settings.contains("workspace-layout/legacy/toolbar-locked"):
                self.settings.setValue(
                    "workspace-layout/legacy/toolbar-locked", self.settings.value(legacy_lock)
                )
            if not self.settings.contains(lock_key):
                locked = self.settings.value(legacy_lock, type=bool)
                if isinstance(locked, bool):
                    self.settings.setValue(lock_key, locked)
        self.settings.setValue(_MIGRATED, True)
        self.settings.sync()
