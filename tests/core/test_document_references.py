# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Reference identity and cycle validation do not require a CAD backend."""

from copy import deepcopy

import pytest

from mycad.core.document_references import (
    DocumentReference,
    archive_fingerprint,
    validate_reference_tree,
)
from mycad.core.exceptions import ValidationError


def archive(identity: str) -> dict[str, object]:
    return {
        "format": "mycad.document",
        "version": 4,
        "file_id": identity,
        "document_kind": "part",
        "document_type": "part",
        "metadata": {},
        "commands": [],
        "named_groups": [],
        "provenance": {
            "mycad": {"version": "test", "source_revision": "test"},
            "python": {"implementation": "test", "version": "test"},
            "dependencies": {"build123d": "test", "ocp": "test", "occt": "test"},
            "units": {"length": "mm", "angle": "deg"},
            "geometry_policy_version": "1",
            "plugins": [],
        },
    }


def test_adopted_snapshot_is_copied_and_fingerprint_is_verified() -> None:
    source = archive("11111111111141118111111111111111")
    params: dict[str, object] = {
        "reference_id": "22222222222242228222222222222222",
        "file_id": source["file_id"],
        "kind": "part",
        "path": "part.my3d",
        "object_id": "",
        "fingerprint": archive_fingerprint(source),
        "archive": source,
    }
    ref = DocumentReference.from_mapping(params)
    original = deepcopy(ref.archive)
    source["metadata"] = {"notes": "mutated"}
    assert ref.archive == original
    with pytest.raises(ValidationError, match="fingerprint"):
        DocumentReference.from_mapping(params)


def test_reference_cycle_is_detected_by_identity_even_with_finite_snapshots() -> None:
    a = archive("11111111111141118111111111111111")
    b = archive("22222222222242228222222222222222")
    b_snapshot = deepcopy(b)
    a["commands"] = [{"id": "reference.attach", "params": {"archive": b_snapshot}}]
    b["commands"] = [{"id": "reference.attach", "params": {"archive": a}}]
    with pytest.raises(ValidationError, match="cyclic"):
        validate_reference_tree(b)
