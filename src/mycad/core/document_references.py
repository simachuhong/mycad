# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""File identities and adopted replay snapshots, independent of paths/backends."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from mycad.core.document_kinds import DocumentKind
from mycad.core.exceptions import ValidationError

REFERENCE_COMMAND_IDS = frozenset({"reference.attach", "reference.update", "reference.detach"})


def archive_fingerprint(archive: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(archive), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DocumentReference:
    reference_id: str
    file_id: str
    kind: DocumentKind
    path: str
    object_id: str
    fingerprint: str
    archive: dict[str, object]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DocumentReference:
        from mycad.core.schema_v4 import validate_archive_v4

        keys = ("reference_id", "file_id", "kind", "path", "object_id", "fingerprint", "archive")
        if set(value) != set(keys) or any(not isinstance(value[k], str) for k in keys[:-1]):
            raise ValidationError("reference: invalid fields")
        archive = value["archive"]
        validate_archive_v4(archive)
        archive = deepcopy(cast("dict[str, object]", archive))
        if value["file_id"] != archive["file_id"] or value["kind"] != archive["document_kind"]:
            raise ValidationError("reference file_id/kind does not match source identity")
        if value["kind"] not in ("sketch", "part"):
            raise ValidationError("reference source must be a sketch or part")
        if value["fingerprint"] != archive_fingerprint(archive):
            raise ValidationError("reference fingerprint does not match adopted source")
        try:
            identity = cast("str", value["reference_id"])
            if identity not in (UUID(identity).hex, str(UUID(identity))):
                raise ValueError("noncanonical UUID")
        except ValueError as exc:
            raise ValidationError("reference_id must be a canonical UUID") from exc
        if value["kind"] == "sketch" and not value["object_id"]:
            raise ValidationError("sketch reference requires object_id")
        return cls(
            identity,
            cast("str", value["file_id"]),
            cast("DocumentKind", value["kind"]),
            cast("str", value["path"]),
            cast("str", value["object_id"]),
            cast("str", value["fingerprint"]),
            archive,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "reference_id": self.reference_id,
            "file_id": self.file_id,
            "kind": self.kind,
            "path": self.path,
            "object_id": self.object_id,
            "fingerprint": self.fingerprint,
            "archive": deepcopy(self.archive),
        }


def validate_reference_tree(
    root: Mapping[str, object], ancestors: frozenset[str] = frozenset()
) -> None:
    """Reject cyclic identities before source replay, including embedded snapshots."""
    identity = cast("str", root["file_id"])
    if identity in ancestors:
        raise ValidationError("cyclic document reference")
    visited = ancestors | {identity}
    for raw in cast("list[dict[str, object]]", root["commands"]):
        if raw["id"] in ("reference.attach", "reference.update"):
            params = cast("dict[str, object]", raw["params"])
            source = params.get("archive")
            if not isinstance(source, dict):
                raise ValidationError("reference archive must be an object")
            source = cast("dict[str, object]", source)
            if not isinstance(source.get("file_id"), str) or not isinstance(
                source.get("commands"), list
            ):
                raise ValidationError("reference archive is missing identity/history")
            validate_reference_tree(source, visited)
