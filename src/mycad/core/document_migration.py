# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Split legacy mixed archives without losing the original audit history."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from mycad.core.document_references import archive_fingerprint
from mycad.core.schema_v4 import validate_archive_v4

PAPER_PREFIXES = ("drawing.sheet.", "drawing.view.", "drawing.annotation.", "drawing.note.")


def migrate_archive(
    root: Mapping[str, object], provenance: object
) -> tuple[dict[str, object], ...]:
    commands = deepcopy(cast("list[dict[str, object]]", root["commands"]))
    source_commands = [c for c in commands if not str(c["id"]).startswith(PAPER_PREFIXES)]
    paper_commands = [c for c in commands if str(c["id"]).startswith(PAPER_PREFIXES)]

    def build(kind: str, history: list[dict[str, object]]) -> dict[str, object]:
        captured = deepcopy(cast("dict[str, object]", root.get("provenance", provenance)))
        history_keys = {(c["id"], c["version"]) for c in history}
        captured["plugins"] = [
            record
            for record in cast("list[dict[str, object]]", captured.get("plugins", []))
            if (record["command_id"], record["command_version"]) in history_keys
        ]
        result: dict[str, object] = {
            "format": "mycad.document",
            "version": 4,
            "file_id": uuid4().hex,
            "document_kind": kind,
            "document_type": "part" if kind == "part" else "drawing2d",
            "metadata": deepcopy(root["metadata"]),
            "commands": history,
            "named_groups": deepcopy(root["named_groups"]) if kind == "part" else [],
            "provenance": captured,
            "migration_origin": deepcopy(dict(root)),
            "reference_locations": {},
        }
        for ordinal, command in enumerate(history):
            command["ordinal"] = ordinal
        return result

    source_kind = "sketch" if root.get("document_type") == "drawing2d" else "part"
    source = build(source_kind, source_commands)
    validate_archive_v4(source)
    if not paper_commands:
        return (source,)
    references: list[dict[str, object]] = []
    objects = (
        [
            str(cast("dict[str, object]", c["params"])["sketch_id"])
            for c in source_commands
            if c["id"] == "sketch.create"
        ]
        if source_kind == "sketch"
        else [""]
    )
    for object_id in objects:
        references.append(
            {
                "id": "reference.attach",
                "version": 1,
                "ordinal": len(references),
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "confirmed_by": "migration",
                "params": {
                    "reference_id": object_id if object_id else uuid4().hex,
                    "file_id": source["file_id"],
                    "kind": source_kind,
                    "path": "",
                    "object_id": object_id,
                    "fingerprint": archive_fingerprint(source),
                    "archive": deepcopy(source),
                },
            }
        )
    drawing = build("drawing", references + paper_commands)
    validate_archive_v4(drawing)
    return source, drawing
