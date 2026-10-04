# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""normalize_params tests: delete-empty-string selector keys at ANY nesting
depth, "key omitted" as the only canonical form, strict idempotence.

Matrix (plan lines 233 + 246-247): the three nesting positions, EdgeSelector
curve handling, the defensive plane error, the validate->normalize->validate
closed loop, wire-forgery nulls rejected at validation, and untouched keys.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from mycad.commands.validation import normalize_params, validate_params
from mycad.core.exceptions import ValidationError
from tests.commands._fixtures import DEFS, fillet_spec, hole_pattern_spec, hole_spec


def _hole_params(face: object) -> dict[str, object]:
    return {
        "target_face": face,
        "position": {"kind": "center"},
        "diameter": 20,
        "depth": {"kind": "through_all"},
    }


# ---------------------------------------------------------------------------
# (1) FaceSelector axis == "" deleted at three nesting positions
# ---------------------------------------------------------------------------


def test_axis_empty_deleted_at_hole_target_face() -> None:
    params = _hole_params({"surface": "cylinder", "axis": ""})
    normalized = normalize_params(params)
    assert "axis" not in cast("dict[str, object]", normalized["target_face"])
    assert normalized["target_face"] == {"surface": "cylinder"}


def test_axis_empty_deleted_at_hole_pattern_base_hole() -> None:
    params: dict[str, object] = {
        "base_hole": _hole_params({"surface": "cylinder", "axis": ""}),
        "pattern": {"kind": "polar", "radius": 25, "count": 4, "start_angle_deg": 0.0},
    }
    normalized = normalize_params(params)
    base_hole = cast("dict[str, object]", normalized["base_hole"])
    assert "axis" not in cast("dict[str, object]", base_hole["target_face"])
    assert base_hole["target_face"] == {"surface": "cylinder"}


def test_axis_empty_deleted_inside_fillet_parent_faces() -> None:
    params: dict[str, object] = {
        "edges": [
            {
                "parent_faces": [
                    {"surface": "cylinder", "axis": ""},
                    {"surface": "plane", "axis": "-Y", "rank": 3},
                ],
                "curve": "circle",
            }
        ],
        "radius": 2,
    }
    normalized = normalize_params(params)
    edges = cast("list[object]", normalized["edges"])
    edge0 = cast("dict[str, object]", edges[0])
    faces = cast("list[object]", edge0["parent_faces"])
    face0 = cast("dict[str, object]", faces[0])
    face1 = cast("dict[str, object]", faces[1])
    assert "axis" not in face0
    assert face0 == {"surface": "cylinder"}
    assert face1 == {"surface": "plane", "axis": "-Y", "rank": 3}


# ---------------------------------------------------------------------------
# (2) EdgeSelector curve == "" deleted; missing stays missing
# ---------------------------------------------------------------------------


def test_curve_empty_deleted() -> None:
    normalized = normalize_params({"parent_faces": [{"surface": "cylinder"}], "curve": ""})
    assert "curve" not in normalized
    assert normalized == {"parent_faces": [{"surface": "cylinder"}]}


def test_curve_missing_stays_missing() -> None:
    normalized = normalize_params({"parent_faces": [{"surface": "plane", "axis": "+Z"}]})
    assert "curve" not in normalized
    assert normalized["parent_faces"] == [{"surface": "plane", "axis": "+Z"}]


def test_curve_nonempty_kept() -> None:
    normalized = normalize_params({"parent_faces": [{"surface": "cylinder"}], "curve": "circle"})
    assert normalized["curve"] == "circle"


# ---------------------------------------------------------------------------
# (3) defensive error: plane + axis == ""
# ---------------------------------------------------------------------------


def test_plane_with_empty_axis_raises_defensively() -> None:
    with pytest.raises(ValidationError, match="plane"):
        normalize_params({"surface": "plane", "axis": ""})


# ---------------------------------------------------------------------------
# (4) idempotent closed loop: validate -> normalize -> validate
# ---------------------------------------------------------------------------


def test_validate_normalize_validate_closed_loop_cylinder_face() -> None:
    params = _hole_params({"surface": "cylinder", "axis": ""})
    once = validate_params(hole_spec(), params, DEFS)
    normalized = normalize_params(once)
    twice = validate_params(hole_spec(), normalized, DEFS)
    assert twice == normalized
    # normalize is idempotent on its own output
    assert normalize_params(normalized) == normalized
    # input mapping untouched
    assert cast("dict[str, object]", params["target_face"])["axis"] == ""


def test_validate_normalize_validate_closed_loop_edge_curve() -> None:
    params: dict[str, object] = {
        "edges": [{"parent_faces": [{"surface": "cylinder", "axis": ""}], "curve": ""}],
        "radius": 2,
    }
    once = validate_params(fillet_spec(), params, DEFS)
    normalized = normalize_params(once)
    twice = validate_params(fillet_spec(), normalized, DEFS)
    assert twice == normalized
    assert normalize_params(normalized) == normalized


def test_normalize_twice_equals_once_for_pattern() -> None:
    params: dict[str, object] = {
        "base_hole": _hole_params({"surface": "cylinder", "axis": ""}),
        "pattern": {"kind": "polar", "radius": 25, "count": 4},
    }
    once = validate_params(hole_pattern_spec(), params, DEFS)
    normalized = normalize_params(once)
    assert normalize_params(normalized) == normalized


# ---------------------------------------------------------------------------
# (5) wire forgery: explicit nulls rejected at VALIDATION stage
# ---------------------------------------------------------------------------


def test_explicit_null_axis_rejected_at_validation() -> None:
    with pytest.raises(ValidationError, match="axis"):
        validate_params(hole_spec(), _hole_params({"surface": "cylinder", "axis": None}), DEFS)


def test_explicit_null_curve_rejected_at_validation() -> None:
    params: dict[str, object] = {
        "edges": [{"parent_faces": [{"surface": "cylinder", "axis": ""}], "curve": None}],
        "radius": 2,
    }
    with pytest.raises(ValidationError, match="curve"):
        validate_params(fillet_spec(), params, DEFS)


# ---------------------------------------------------------------------------
# (6) untouched keys deep-equal; no None-valued axis/curve anywhere
# ---------------------------------------------------------------------------


def _collect_axis_curve_values(node: object, out: list[object]) -> None:
    if isinstance(node, dict):
        for key, value in cast("dict[str, object]", node).items():
            if key in ("axis", "curve"):
                out.append(value)
            _collect_axis_curve_values(value, out)
    elif isinstance(node, list):
        for item in cast("list[object]", node):
            _collect_axis_curve_values(item, out)


def test_untouched_keys_deep_equal_and_no_none_axis_curve() -> None:
    params: dict[str, object] = {
        "base_hole": {
            "target_face": {"surface": "cylinder", "axis": "", "rank": 2},
            "position": {"kind": "center"},
            "diameter": 6,
            "depth": {"kind": "blind", "value": 3.0},
        },
        "pattern": {"kind": "polar", "radius": 25, "count": 4, "start_angle_deg": 0.0},
    }
    validated = validate_params(hole_pattern_spec(), params, DEFS)
    normalized = normalize_params(validated)
    base_hole = cast("dict[str, object]", normalized["base_hole"])
    target = cast("dict[str, object]", base_hole["target_face"])
    # rank kept, axis gone
    assert target == {"surface": "cylinder", "rank": 2}
    # every other key deep-equal to the validated input
    expected = {
        "base_hole": {
            "target_face": {"surface": "cylinder", "rank": 2},
            "position": {"kind": "center"},
            "diameter": 6,
            "depth": {"kind": "blind", "value": 3.0},
        },
        "pattern": {"kind": "polar", "radius": 25, "count": 4, "start_angle_deg": 0.0},
    }
    assert normalized == expected
    values: list[object] = []
    _collect_axis_curve_values(normalized, values)
    assert values == []  # deleted keys leave no None behind anywhere


def test_normalize_returns_plain_dict_types() -> None:
    normalized = normalize_params(
        {"parent_faces": [{"surface": "cylinder", "axis": ""}], "curve": ""}
    )
    assert type(normalized) is dict
    faces = cast("list[object]", normalized["parent_faces"])
    assert type(faces) is list
    assert type(faces[0]) is dict


def test_normalize_is_pure_against_input() -> None:
    original: dict[str, object] = {
        "parent_faces": [{"surface": "cylinder", "axis": ""}],
        "curve": "",
    }
    snapshot: Mapping[str, object] = {
        "parent_faces": [{"surface": "cylinder", "axis": ""}],
        "curve": "",
    }
    normalize_params(original)
    assert original == snapshot
