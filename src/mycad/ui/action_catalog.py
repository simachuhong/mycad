# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Stable UI identities referencing the existing shared Qt actions."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction


class ActionCatalog(QObject):
    """Associate one stable identifier with one action object."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._actions: dict[str, QAction] = {}

    def register(self, action_id: str, action: QAction) -> None:
        existing = self._actions.get(action_id)
        if existing is not None and existing is not action:
            raise ValueError(f"UI action already registered: {action_id}")
        if existing is action:
            return
        self._actions[action_id] = action
        self.changed.emit()

    def get(self, action_id: str) -> QAction:
        return self._actions[action_id]

    def find(self, action_id: str) -> QAction | None:
        """Return the shared action, or None for an unavailable contribution."""
        return self._actions.get(action_id)

    def entries(self) -> tuple[tuple[str, QAction], ...]:
        """List registered identities without exposing the mutable registry."""
        return tuple(self._actions.items())

    def unregister(self, action_id: str) -> QAction | None:
        """Remove a contribution without destroying the action owned by its provider."""
        action = self._actions.pop(action_id, None)
        if action is not None:
            self.changed.emit()
        return action
