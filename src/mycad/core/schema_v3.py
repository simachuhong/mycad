# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Strict v3 archive validation with an explicit document kind."""

from __future__ import annotations

from typing import cast

from mycad.core.document_kinds import DRAWING2D_COMMAND_IDS
from mycad.core.exceptions import ValidationError
from mycad.core.schema_v2 import validate_archive_v2

ARCHIVE_VERSION_V3 = 3


def validate_archive_v3(data: object) -> None:
    """Validate v3 provenance and the required ``part``/``drawing2d`` kind."""
    if not isinstance(data, dict):
        raise ValidationError("archive: top level must be an object")
    root = cast("dict[str, object]", data)
    version = root.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != ARCHIVE_VERSION_V3:
        raise ValidationError("archive/version: expected integer 3")
    document_type = root.get("document_type")
    if document_type not in ("part", "drawing2d"):
        raise ValidationError("archive/document_type: expected 'part' or 'drawing2d'")

    v2_payload = {key: value for key, value in root.items() if key != "document_type"}
    v2_payload["version"] = 2
    validate_archive_v2(v2_payload)

    if document_type == "drawing2d":
        if cast("list[object]", root["named_groups"]):
            raise ValidationError("archive/named_groups: drawing2d cannot contain 3D named groups")
        for index, raw_command in enumerate(cast("list[object]", root["commands"])):
            command = cast("dict[str, object]", raw_command)
            command_id = cast("str", command["id"])
            if command_id not in DRAWING2D_COMMAND_IDS:
                raise ValidationError(
                    f"archive/commands/{index}: drawing2d cannot contain command {command_id!r}"
                )
            if command_id.startswith("reference."):
                raise ValidationError("archive/commands: document references require v4")


__all__ = ["ARCHIVE_VERSION_V3", "validate_archive_v3"]
