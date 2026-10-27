# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Strict v2 archive validation keeps the frozen v1 wire contract intact."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import cast

import pytest

from mycad.core.exceptions import ValidationError
from mycad.core.schema_v2 import validate_archive_v2


def _archive() -> dict[str, object]:
    return {
        "format": "mycad.document",
        "version": 2,
        "metadata": {"part_no": "", "revision": "", "material": "", "source": "local"},
        "commands": [],
        "named_groups": [],
        "provenance": {
            "mycad": {"version": "0.1.0", "source_revision": "unavailable"},
            "python": {"implementation": "CPython", "version": "3.12.0"},
            "dependencies": {
                "build123d": "0.11.1",
                "ocp": "7.9.3.1",
                "occt": "unavailable",
                "planegcs": "0.9.6",
            },
            "units": {"length": "mm", "angle": "deg"},
            "geometry_policy_version": "1",
            "plugins": [],
        },
    }


def test_v2_archive_accepts_complete_provenance() -> None:
    validate_archive_v2(_archive())


def test_v2_archive_without_optional_solver_provenance_remains_readable() -> None:
    data = _archive()
    cast("dict[str, object]", cast("dict[str, object]", data["provenance"])["dependencies"]).pop(
        "planegcs"
    )

    validate_archive_v2(data)


def _remove_dependencies(data: dict[str, object]) -> None:
    cast("dict[str, object]", data["provenance"]).pop("dependencies")


def _set_length_unit(data: dict[str, object]) -> None:
    cast("dict[str, object]", cast("dict[str, object]", data["provenance"])["units"])["length"] = (
        "inch"
    )


def _add_unknown_provenance(data: dict[str, object]) -> None:
    cast("dict[str, object]", data["provenance"])["unexpected"] = True


def _add_unknown_top_level(data: dict[str, object]) -> None:
    data["unexpected"] = True


def _set_future_version(data: dict[str, object]) -> None:
    data["version"] = 3


_MUTATIONS: tuple[tuple[Callable[[dict[str, object]], None], str], ...] = (
    (_remove_dependencies, "dependencies"),
    (_set_length_unit, "units/length"),
    (_add_unknown_provenance, "unknown key"),
    (_add_unknown_top_level, "unknown key"),
    (_set_future_version, "version"),
)


@pytest.mark.parametrize(("mutate", "message"), _MUTATIONS)
def test_v2_archive_rejects_incomplete_or_unknown_data(
    mutate: Callable[[dict[str, object]], None], message: str
) -> None:
    data = deepcopy(_archive())
    mutate(data)
    with pytest.raises(ValidationError, match=message):
        validate_archive_v2(data)
