# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""V5 adds instance identity per command, retaining all six audit fields."""

from __future__ import annotations

from typing import cast

from mycad.core.command_identity import require_instance_id
from mycad.core.exceptions import ValidationError
from mycad.core.schema_v4 import validate_archive_v4

ARCHIVE_VERSION_V5 = 5


def validate_archive_v5(data: object, *, max_reference_version: int = 5) -> None:
    if not isinstance(data, dict):
        raise ValidationError("archive: expected object")
    root = cast("dict[str, object]", data)
    if type(root.get("version")) is not int or root["version"] != 5:
        raise ValidationError("archive/version: expected integer 5")
    raw = root.get("commands")
    if not isinstance(raw, list):
        raise ValidationError("archive/commands: expected array")
    identities: set[str] = set()
    previous_commands: list[dict[str, object]] = []
    for entry in cast("list[object]", raw):
        if not isinstance(entry, dict):
            raise ValidationError("archive/commands: expected object")
        command = cast("dict[str, object]", entry)
        identity = require_instance_id(command.get("instance_id"))
        if identity in identities:
            raise ValidationError("duplicate command instance_id")
        identities.add(identity)
        previous_commands.append({k: v for k, v in command.items() if k != "instance_id"})
    previous = {**root, "version": 4, "commands": previous_commands}
    validate_archive_v4(previous, max_reference_version=max_reference_version)
