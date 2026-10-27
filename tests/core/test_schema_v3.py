# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Strict schema and document-kind rules for archive v3."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import cast

import pytest

from mycad.core.exceptions import ValidationError
from mycad.core.schema_v3 import validate_archive_v3


def _archive(document_type: str = "drawing2d") -> dict[str, object]:
    return {
        "format": "mycad.document",
        "version": 3,
        "document_type": document_type,
        "metadata": {"part_no": "", "revision": "", "material": "", "source": "local"},
        "commands": [],
        "named_groups": [],
        "provenance": {
            "mycad": {"version": "0.1.0", "source_revision": "unavailable"},
            "python": {"implementation": "CPython", "version": "3.12.0"},
            "dependencies": {
                "build123d": "unavailable",
                "ocp": "unavailable",
                "occt": "unavailable",
            },
            "units": {"length": "mm", "angle": "deg"},
            "geometry_policy_version": "1",
            "plugins": [],
        },
    }


def _remove_document_type(data: dict[str, object]) -> object:
    return data.pop("document_type")


def _set_unknown_document_type(data: dict[str, object]) -> None:
    data["document_type"] = "assembly"


def _set_old_version(data: dict[str, object]) -> None:
    data["version"] = 2


def _add_unknown_field(data: dict[str, object]) -> None:
    data["unexpected"] = True


def _add_3d_named_group(data: dict[str, object]) -> None:
    cast("list[object]", data["named_groups"]).append(
        {"name": "solid-faces", "faces": [], "edges": []}
    )


_MUTATIONS: tuple[tuple[Callable[[dict[str, object]], object], str], ...] = (
    (_remove_document_type, "document_type"),
    (_set_unknown_document_type, "document_type"),
    (_set_old_version, "version"),
    (_add_unknown_field, "unknown key"),
    (_add_3d_named_group, "drawing2d cannot contain 3D named groups"),
)


def test_v3_accepts_part_and_independent_drawing_types() -> None:
    validate_archive_v3(_archive("part"))
    validate_archive_v3(_archive("drawing2d"))


@pytest.mark.parametrize(("mutate", "message"), _MUTATIONS)
def test_v3_rejects_unknown_or_malformed_document_kind(
    mutate: Callable[[dict[str, object]], object], message: str
) -> None:
    data = deepcopy(_archive())
    mutate(data)
    with pytest.raises(ValidationError, match=message):
        validate_archive_v3(data)


def test_v3_rejects_non_sketch_commands_in_independent_drawing() -> None:
    data = _archive()
    cast("list[object]", data["commands"]).append(
        {
            "id": "feature.box",
            "version": 1,
            "params": {},
            "ordinal": 0,
            "timestamp_utc": "2026-10-25T00:00:00+00:00",
            "confirmed_by": None,
        }
    )
    with pytest.raises(ValidationError, match="drawing2d.*feature.box"):
        validate_archive_v3(data)
