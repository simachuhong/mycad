# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Persistent file identity and explicit workspace-document kind."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from mycad.core.document_references import DocumentReference, validate_reference_tree
from mycad.core.exceptions import ValidationError
from mycad.core.schema_v3 import validate_archive_v3

ARCHIVE_VERSION_V4 = 4


def validate_archive_v4(data: object, *, max_reference_version: int = 4) -> None:
    if not isinstance(data, dict):
        raise ValidationError("archive: expected object")
    root = cast("dict[str, object]", data)
    if type(root.get("version")) is not int or root["version"] != 4:
        raise ValidationError("archive/version: expected integer 4")
    identity = root.get("file_id")
    if not isinstance(identity, str):
        raise ValidationError("archive/file_id: expected UUID")
    try:
        parsed = UUID(identity)
    except ValueError as exc:
        raise ValidationError("archive/file_id: expected UUID") from exc
    if identity not in (parsed.hex, str(parsed)):
        raise ValidationError("archive/file_id: expected canonical UUID")
    kind = root.get("document_kind")
    if kind not in ("sketch", "drawing", "part"):
        raise ValidationError("archive/document_kind: unsupported kind")
    if root.get("document_type") != ("part" if kind == "part" else "drawing2d"):
        raise ValidationError("archive/document_kind: inconsistent kind and document_type")
    previous = {
        k: v
        for k, v in root.items()
        if k not in ("file_id", "document_kind", "migration_origin", "reference_locations")
    }
    previous["version"] = 3
    # References are v4-only. Validate their outer history fields using v3's
    # part contract, then apply the drawing command gate explicitly below.
    previous["document_type"] = "part"
    validate_archive_v3(previous)
    if kind != "part":
        from mycad.core.document_kinds import DRAWING2D_COMMAND_IDS

        if root["named_groups"]:
            raise ValidationError("drawing document cannot contain 3D named groups")
        for command in cast("list[dict[str, object]]", root["commands"]):
            if command["id"] not in DRAWING2D_COMMAND_IDS:
                raise ValidationError("drawing document cannot contain solid commands")
    validate_reference_tree(root, max_archive_version=max_reference_version)
    # Validate adopted bytes and their fingerprint before any kernel is reset.
    # The cycle/version walk above must precede recursive schema dispatch.
    for command in cast("list[dict[str, object]]", root["commands"]):
        if command["id"] in ("reference.attach", "reference.update"):
            DocumentReference.from_mapping(cast("dict[str, object]", command["params"]))
    if kind != "drawing" and any(
        str(c["id"]).startswith(
            ("drawing.sheet.", "drawing.view.", "drawing.annotation.", "drawing.note.")
        )
        for c in cast("list[dict[str, object]]", root["commands"])
    ):
        raise ValidationError("engineering drawing objects require the drawing document kind")
    origin = root.get("migration_origin")
    if origin is not None:
        from mycad.core.schema_v1 import validate_archive
        from mycad.core.schema_v2 import validate_archive_v2

        if not isinstance(origin, dict):
            raise ValidationError("migration_origin must be a legacy archive")
        origin = cast("dict[str, object]", origin)
        validator = {1: validate_archive, 2: validate_archive_v2, 3: validate_archive_v3}.get(
            cast("int", origin.get("version"))
        )
        if validator is None:
            raise ValidationError("migration_origin must be v1/v2/v3")
        validator(origin)
    locations = root.get("reference_locations", {})
    if not isinstance(locations, dict) or any(
        not isinstance(k, str) or not isinstance(v, str)
        for k, v in cast("dict[object, object]", locations).items()
    ):
        raise ValidationError("reference_locations must map file identities to path strings")
