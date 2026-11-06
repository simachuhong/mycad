# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Persistent recent-document metadata, independent of the files themselves."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from PySide6.QtCore import QSettings

from mycad.core.document_kinds import DocumentKind
from mycad.ui.path_identity import path_identity

_KEY = "recent/documents_v1"
_LIMIT = 20


@dataclass(frozen=True)
class RecentDocument:
    path: Path
    kind: DocumentKind
    opened_at: str


def _key(path: Path) -> str:
    return path_identity(path)


class RecentDocuments:
    def __init__(self, settings: QSettings) -> None:
        self.settings = settings

    @property
    def items(self) -> tuple[RecentDocument, ...]:
        raw = self.settings.value(_KEY, "[]")
        if not isinstance(raw, str):
            return ()
        try:
            value: object = json.loads(raw)
        except (TypeError, ValueError):
            return ()
        if not isinstance(value, list):
            return ()
        result: list[RecentDocument] = []
        for item in cast("list[object]", value):
            if not isinstance(item, dict):
                continue
            row = cast("dict[str, object]", item)
            path, kind, opened_at = row.get("path"), row.get("kind"), row.get("opened_at")
            if (
                isinstance(path, str)
                and path
                and kind in ("sketch", "drawing", "part")
                and isinstance(opened_at, str)
                and opened_at
            ):
                result.append(RecentDocument(Path(path), kind, opened_at))
        return tuple(result[:_LIMIT])

    def add(self, path: Path, kind: DocumentKind) -> None:
        record = RecentDocument(path.absolute(), kind, datetime.now(UTC).isoformat())
        self._write((record, *(r for r in self.items if _key(r.path) != _key(path))))

    def remove(self, path: Path) -> None:
        self._write(tuple(r for r in self.items if _key(r.path) != _key(path)))

    def clear(self) -> None:
        self._write(())

    def _write(self, records: tuple[RecentDocument, ...]) -> None:
        value = [
            {"path": str(r.path), "kind": r.kind, "opened_at": r.opened_at}
            for r in records[:_LIMIT]
        ]
        self.settings.setValue(_KEY, json.dumps(value, ensure_ascii=False))
        self.settings.sync()
