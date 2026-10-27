# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Contract checks for the representative-part scenario catalog."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import cast

from mycad.builtin_commands import BUILTIN_COMMAND_IDS

CATALOG_PATH = Path(__file__).parents[2] / "examples" / "representative_parts.json"
EXPECTED_STATUSES = {"supported", "expected_rejection", "extension_candidate"}
EXPECTED_CATEGORIES = {
    "flange",
    "shaft_sleeve",
    "mounting_plate",
    "cover",
    "boundary",
}


def _catalog() -> list[dict[str, object]]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return cast("list[dict[str, object]]", data)


def test_catalog_has_stable_unique_ids_and_expected_coverage() -> None:
    cases = _catalog()
    ids = [case["id"] for case in cases]
    assert len(cases) == 30
    assert len(ids) == len(set(ids))
    assert all(isinstance(case_id, str) and case_id for case_id in ids)
    assert {case["category"] for case in cases} == EXPECTED_CATEGORIES
    assert Counter(case["status"] for case in cases) == {
        "supported": 18,
        "expected_rejection": 6,
        "extension_candidate": 6,
    }


def test_catalog_command_chains_are_registered_and_classifications_are_honest() -> None:
    cases = _catalog()
    known_ids = set(BUILTIN_COMMAND_IDS)
    for case in cases:
        assert case["status"] in EXPECTED_STATUSES
        assert isinstance(case["name"], str) and case["name"].strip()
        assert isinstance(case["acceptance"], str) and case["acceptance"].strip()
        commands = case["commands"]
        assert isinstance(commands, list)
        command_ids = cast("list[object]", commands)
        assert all(isinstance(command_id, str) for command_id in command_ids)
        assert all(cast("str", command_id) in known_ids for command_id in command_ids)
        if case["status"] == "supported":
            assert commands, f"supported case {case['id']} needs a registered chain"
