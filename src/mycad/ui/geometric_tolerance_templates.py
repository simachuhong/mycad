# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""User-local named templates for geometric tolerance rows."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

from PySide6.QtCore import QSettings

from mycad.core.geometric_tolerance import ToleranceRow

_KEY = "drawing2d/toleranceTemplates"


def _name(value: str) -> str:
    if not value or value != value.strip() or len(value) > 80 or not value.isprintable():
        raise ValueError("模板名称必须为 1–80 个可打印字符，且不能有首尾空格。")
    return value


class ToleranceTemplateStore:
    """Store templates locally without retaining identities from the source drawing."""

    def __init__(self, settings: QSettings) -> None:
        self.settings = settings

    def _read(self) -> dict[str, tuple[ToleranceRow, ...]]:
        raw = self.settings.value(_KEY)
        if raw is None:
            return {}
        try:
            if not isinstance(raw, str) or len(raw) > 1024 * 1024:
                raise ValueError
            root: object = json.loads(raw)
            if not isinstance(root, dict):
                raise ValueError
            data = cast("dict[str, object]", root)
            if set(data) != {"version", "templates"}:
                raise ValueError
            raw_templates = data["templates"]
            if data["version"] != 1 or not isinstance(raw_templates, dict):
                raise ValueError
            templates = cast("dict[object, object]", raw_templates)
            if len(templates) > 100:
                raise ValueError
            result: dict[str, tuple[ToleranceRow, ...]] = {}
            for name, value in templates.items():
                if not isinstance(name, str) or not isinstance(value, list):
                    raise ValueError
                _name(name)
                items = cast("list[object]", value)
                if not 1 <= len(items) <= 16 or name.casefold() in {
                    existing.casefold() for existing in result
                }:
                    raise ValueError
                rows = tuple(ToleranceRow.from_mapping(item) for item in items)
                if any(ref.datum_id is not None for row in rows for ref in row.datums):
                    raise ValueError
                result[name] = rows
            return result
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise ValueError("公差模板数据损坏或版本不受支持，未修改原数据。") from exc

    def _write(self, templates: dict[str, tuple[ToleranceRow, ...]]) -> None:
        payload = {
            "version": 1,
            "templates": {
                name: [row.to_mapping() for row in rows] for name, rows in templates.items()
            },
        }
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        if len(encoded) > 1024 * 1024:
            raise ValueError("公差模板数据过大。")
        self.settings.setValue(_KEY, encoded)
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            raise ValueError("无法保存公差模板设置。")

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._read(), key=str.casefold))

    def get(self, name: str) -> tuple[ToleranceRow, ...]:
        try:
            return self._read()[name]
        except KeyError as exc:
            raise ValueError("公差模板不存在。") from exc

    def save(self, name: str, rows: tuple[ToleranceRow, ...]) -> None:
        _name(name)
        templates = self._read()
        if any(existing.casefold() == name.casefold() for existing in templates):
            raise ValueError("模板名称已存在。")
        if len(templates) >= 100 or not 1 <= len(rows) <= 16:
            raise ValueError("模板数量或公差行数超出限制。")
        templates[name] = tuple(
            replace(row, datums=tuple(replace(ref, datum_id=None) for ref in row.datums))
            for row in rows
        )
        self._write(templates)

    def delete(self, name: str) -> None:
        templates = self._read()
        if name not in templates:
            raise ValueError("公差模板不存在。")
        del templates[name]
        self._write(templates)
