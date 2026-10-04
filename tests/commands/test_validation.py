# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""validate_params tests: the FIXED JSON-Schema subset, exactly as mandated by
plan lines 229-232 and the T3 acceptance matrix.

Every keyword in the fixed subset has a positive and (where meaningful) a
negative case; any keyword outside the subset must raise instead of being
silently ignored; error messages must carry dotted field paths.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.commands.validation import validate_params
from mycad.core.exceptions import ValidationError
from tests.commands._fixtures import (
    DEFS,
    cylinder_spec,
    extrude_spec,
    fillet_spec,
    hole_spec,
)


def _spec_with(schema: Mapping[str, object], spec_id: str = "test.synthetic") -> CommandSpec:
    """CommandSpec carrying an arbitrary (test-local) params schema."""
    return CommandSpec(
        id=spec_id,
        version=1,
        summary_en="synthetic",
        label_zh="合成",
        params_schema=schema,
        cli=CliSyntax(verb_aliases=("synthetic",)),
    )


# ---------------------------------------------------------------------------
# Positive: legal params, defaults, $ref resolution
# ---------------------------------------------------------------------------


def test_legal_cylinder_params_pass() -> None:
    result = validate_params(
        cylinder_spec(), {"radius": 40, "height": 8, "center": [0, 0, 0], "mode": "new"}, DEFS
    )
    assert result == {"radius": 40, "height": 8, "center": [0, 0, 0], "mode": "new"}


def test_defaults_filled_through_ref_and_not_overwritten() -> None:
    result = validate_params(cylinder_spec(), {"radius": 40, "height": 8}, DEFS)
    assert result == {"radius": 40, "height": 8, "center": [0.0, 0.0, 0.0], "mode": "new"}
    # explicit values are never overwritten by defaults
    explicit = validate_params(
        cylinder_spec(), {"radius": 1, "height": 2, "center": [5.0, 5.0, 5.0], "mode": "add"}, DEFS
    )
    assert explicit == {"radius": 1, "height": 2, "center": [5.0, 5.0, 5.0], "mode": "add"}


def test_root_level_ref_form_is_legal() -> None:
    params: Mapping[str, object] = {
        "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
        "position": {"kind": "center"},
        "diameter": 20,
        "depth": {"kind": "through_all"},
    }
    result = validate_params(hole_spec(), params, DEFS)
    assert result == dict(params)


def test_input_mapping_is_not_mutated() -> None:
    original: dict[str, object] = {"radius": 40, "height": 8}
    snapshot = dict(original)
    validate_params(cylinder_spec(), original, DEFS)
    assert original == snapshot


# ---------------------------------------------------------------------------
# type / bounds / required / additionalProperties
# ---------------------------------------------------------------------------


def test_type_error_message_carries_dotted_path() -> None:
    with pytest.raises(ValidationError, match=r"edges\.0\.parent_faces\.0\.rank"):
        validate_params(
            fillet_spec(),
            {
                "edges": [
                    {"parent_faces": [{"surface": "plane", "axis": "+Z", "rank": "one"}]},
                ],
                "radius": 2,
            },
            DEFS,
        )


def test_integer_rejects_bool() -> None:
    with pytest.raises(ValidationError, match="rank"):
        validate_params(
            hole_spec(),
            {
                "target_face": {"surface": "plane", "axis": "+Z", "rank": True},
                "position": {"kind": "center"},
                "diameter": 20,
                "depth": {"kind": "through_all"},
            },
            DEFS,
        )


def test_number_rejects_bool_and_string() -> None:
    for bad in (True, "abc", None):
        with pytest.raises(ValidationError, match="radius"):
            validate_params(cylinder_spec(), {"radius": bad, "height": 8}, DEFS)


def test_out_of_bounds_exclusive_minimum() -> None:
    with pytest.raises(ValidationError, match=r"radius.*exclusiveMinimum"):
        validate_params(cylinder_spec(), {"radius": -1, "height": 8}, DEFS)
    # boundary: 0 itself is also rejected (exclusive), 0.001 passes
    with pytest.raises(ValidationError, match="exclusiveMinimum"):
        validate_params(cylinder_spec(), {"radius": 0, "height": 8}, DEFS)
    ok = validate_params(cylinder_spec(), {"radius": 0.001, "height": 8}, DEFS)
    assert ok["radius"] == 0.001


def test_missing_required_key() -> None:
    with pytest.raises(ValidationError, match="required.*radius|radius.*required"):
        validate_params(cylinder_spec(), {"height": 8}, DEFS)
    # nested required
    with pytest.raises(ValidationError, match=r"target_face.*axis|axis.*required"):
        validate_params(
            hole_spec(),
            {
                "target_face": {"surface": "plane"},
                "position": {"kind": "center"},
                "diameter": 20,
                "depth": {"kind": "through_all"},
            },
            DEFS,
        )


def test_unknown_key_rejected_with_dotted_path() -> None:
    with pytest.raises(ValidationError, match=r"^extra: unknown key"):
        validate_params(cylinder_spec(), {"radius": 1, "height": 2, "extra": 1}, DEFS)
    with pytest.raises(ValidationError, match=r"target_face\.bogus: unknown key"):
        validate_params(
            hole_spec(),
            {
                "target_face": {"surface": "plane", "axis": "+Z", "bogus": 1},
                "position": {"kind": "center"},
                "diameter": 20,
                "depth": {"kind": "through_all"},
            },
            DEFS,
        )


def test_enum_error() -> None:
    with pytest.raises(ValidationError, match=r"mode.*banana"):
        validate_params(cylinder_spec(), {"radius": 1, "height": 2, "mode": "banana"}, DEFS)


def test_const_mismatch() -> None:
    with pytest.raises(ValidationError, match=r"target_face\.surface.*plane"):
        validate_params(
            hole_spec(),
            {
                "target_face": {"surface": "sphere", "axis": "+Z"},
                "position": {"kind": "center"},
                "diameter": 20,
                "depth": {"kind": "through_all"},
            },
            DEFS,
        )


def test_items_element_type_error_deep_path() -> None:
    with pytest.raises(ValidationError, match=r"edges\.0\.parent_faces\.0\.axis"):
        validate_params(
            fillet_spec(),
            {
                "edges": [{"parent_faces": [{"surface": "plane", "axis": 7}]}],
                "radius": 2,
            },
            DEFS,
        )


def test_min_items_violation() -> None:
    with pytest.raises(ValidationError, match=r"edges.*minItems"):
        validate_params(fillet_spec(), {"edges": [], "radius": 2}, DEFS)


def test_max_items_violation() -> None:
    with pytest.raises(ValidationError, match=r"center.*maxItems"):
        validate_params(cylinder_spec(), {"radius": 1, "height": 2, "center": [0, 0, 0, 0]}, DEFS)


def test_min_max_length_on_strings() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"name": {"type": "string", "minLength": 2, "maxLength": 4}},
        "additionalProperties": False,
    }
    assert validate_params(_spec_with(schema), {"name": "abc"}) == {"name": "abc"}
    with pytest.raises(ValidationError, match="minLength"):
        validate_params(_spec_with(schema), {"name": "a"})
    with pytest.raises(ValidationError, match="maxLength"):
        validate_params(_spec_with(schema), {"name": "abcde"})


def test_minimum_maximum_inclusive_bounds() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"n": {"type": "number", "minimum": 0, "maximum": 10}},
        "additionalProperties": False,
    }
    for ok in (0, 10, 5):
        assert validate_params(_spec_with(schema), {"n": ok}) == {"n": ok}
    for bad in (-0.1, 10.1):
        with pytest.raises(ValidationError, match="n:"):
            validate_params(_spec_with(schema), {"n": bad})


def test_explicit_null_is_not_replaced_by_default() -> None:
    # default must fill only MISSING keys; explicit null fails the type check
    with pytest.raises(ValidationError, match="center"):
        validate_params(cylinder_spec(), {"radius": 1, "height": 2, "center": None}, DEFS)
    # null against an enum (wire forgery "axis": null) is rejected at validation
    with pytest.raises(ValidationError, match=r"target_face\.axis"):
        validate_params(
            hole_spec(),
            {
                "target_face": {"surface": "cylinder", "axis": None},
                "position": {"kind": "center"},
                "diameter": 20,
                "depth": {"kind": "through_all"},
            },
            DEFS,
        )


# ---------------------------------------------------------------------------
# oneOf discipline
# ---------------------------------------------------------------------------


def test_oneof_each_legal_branch() -> None:
    # Depth: through_all branch
    through: Mapping[str, object] = {
        "target_face": {"surface": "plane", "axis": "+Z"},
        "position": {"kind": "center"},
        "diameter": 20,
        "depth": {"kind": "through_all"},
    }
    assert validate_params(hole_spec(), through, DEFS) == dict(through)
    # Depth: blind branch (fills no defaults; value required)
    blind: Mapping[str, object] = {
        "target_face": {"surface": "plane", "axis": "+Z"},
        "position": {"kind": "center"},
        "diameter": 20,
        "depth": {"kind": "blind", "value": 5.0},
    }
    assert validate_params(hole_spec(), blind, DEFS) == dict(blind)
    # Profile: circle and rect branches (nested default center=[0,0])
    circle = validate_params(
        extrude_spec(), {"profile": {"type": "circle", "radius": 30}, "distance": 10}, DEFS
    )
    assert circle == {
        "profile": {"type": "circle", "radius": 30, "center": [0.0, 0.0]},
        "distance": 10,
        "mode": "new",
    }
    rect = validate_params(
        extrude_spec(),
        {"profile": {"type": "rect", "width": 10, "height": 5}, "distance": -3},
        DEFS,
    )
    assert rect == {
        "profile": {"type": "rect", "width": 10, "height": 5, "center": [0.0, 0.0]},
        "distance": -3,
        "mode": "new",
    }


def test_oneof_unknown_discriminator_zero_branches() -> None:
    with pytest.raises(ValidationError, match=r"depth.*oneOf.*no branch"):
        validate_params(
            hole_spec(),
            {
                "target_face": {"surface": "plane", "axis": "+Z"},
                "position": {"kind": "center"},
                "diameter": 20,
                "depth": {"kind": "banana"},
            },
            DEFS,
        )


def test_oneof_zero_branches_lists_each_branch_first_error() -> None:
    with pytest.raises(ValidationError, match="branch") as exc_info:
        validate_params(
            hole_spec(),
            {
                "target_face": {"surface": "plane", "axis": "+Z"},
                "position": {"kind": "center"},
                "diameter": 20,
                "depth": {"kind": "banana"},
            },
            DEFS,
        )
    msg = str(exc_info.value)
    assert "[0]" in msg and "[1]" in msg


def test_oneof_multiple_branches_rejected() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "sel": {
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {"a": {"const": 1}},
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {"a": {"type": "integer"}},
                        "additionalProperties": False,
                    },
                ]
            }
        },
        "additionalProperties": False,
    }
    # a=1 matches both branches (const 1 == integer 1) -> exactly-one violated
    with pytest.raises(ValidationError, match=r"sel.*oneOf.*2 branches"):
        validate_params(_spec_with(schema), {"sel": {"a": 1}}, DEFS)


# ---------------------------------------------------------------------------
# $ref discipline
# ---------------------------------------------------------------------------


def test_ref_face_selector_position_depth_legal() -> None:
    params: Mapping[str, object] = {
        "target_face": {"surface": "cylinder"},  # axis omitted = all cylinders
        "position": {"kind": "center"},
        "diameter": 20,
        "depth": {"kind": "blind", "value": 3.5},
    }
    result = validate_params(hole_spec(), params, DEFS)
    assert result == dict(params)


def test_ref_bad_prefix_rejected() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"x": {"$ref": "#/definitions/FaceSelector"}},
        "additionalProperties": False,
    }
    with pytest.raises(ValidationError, match=r"\$ref"):
        validate_params(_spec_with(schema), {"x": {"surface": "plane", "axis": "+Z"}}, DEFS)
    remote: dict[str, object] = {
        "type": "object",
        "properties": {"x": {"$ref": "https://example.com/schema.json#/x"}},
        "additionalProperties": False,
    }
    with pytest.raises(ValidationError, match=r"\$ref"):
        validate_params(_spec_with(remote), {"x": 1}, DEFS)


def test_ref_out_of_table_name_rejected() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"x": {"$ref": "#/$defs/NoSuchDef"}},
        "additionalProperties": False,
    }
    with pytest.raises(ValidationError, match="NoSuchDef"):
        validate_params(_spec_with(schema), {"x": 1}, DEFS)


def test_ref_without_defs_table_rejected() -> None:
    with pytest.raises(ValidationError, match=r"\$ref|No such|defs"):
        validate_params(
            hole_spec(),
            {
                "target_face": {"surface": "plane", "axis": "+Z"},
                "position": {"kind": "center"},
                "diameter": 20,
                "depth": {"kind": "through_all"},
            },
        )


def test_inline_defs_shadow_injected_table() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "$defs": {"Mode": {"type": "string", "enum": ["shadowed"]}},
        "properties": {"mode": {"$ref": "#/$defs/Mode"}},
        "additionalProperties": False,
    }
    # injected table's Mode enum does NOT contain "shadowed": inline $defs wins
    assert validate_params(_spec_with(schema), {"mode": "shadowed"}, DEFS) == {"mode": "shadowed"}
    with pytest.raises(ValidationError, match="mode"):
        validate_params(_spec_with(schema), {"mode": "new"}, DEFS)


# ---------------------------------------------------------------------------
# unknown keyword / description
# ---------------------------------------------------------------------------


def test_unknown_schema_keyword_raises() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"x": {"type": "string", "patternProperties": {"^a": True}}},
        "additionalProperties": False,
    }
    with pytest.raises(ValidationError, match="patternProperties"):
        validate_params(_spec_with(schema), {"x": "abc"}, DEFS)
    top: dict[str, object] = {"type": "object", "patternProperties": {"^a": True}}
    with pytest.raises(ValidationError, match="patternProperties"):
        validate_params(_spec_with(top), {}, DEFS)


def test_description_is_doc_only() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "description": "root description is ignored",
        "properties": {"x": {"type": "string", "description": "doc only"}},
        "additionalProperties": False,
    }
    assert validate_params(_spec_with(schema), {"x": "v"}) == {"x": "v"}


# ---------------------------------------------------------------------------
# FaceSelector oneOf branch discipline (matrix items 1-5)
# ---------------------------------------------------------------------------


def _hole_with_face(face: object) -> Mapping[str, object]:
    return {
        "target_face": face,
        "position": {"kind": "center"},
        "diameter": 20,
        "depth": {"kind": "through_all"},
    }


def test_face_selector_plane_with_signed_axis_valid() -> None:
    result = validate_params(hole_spec(), _hole_with_face({"surface": "plane", "axis": "+Z"}), DEFS)
    assert result["target_face"] == {"surface": "plane", "axis": "+Z"}


def test_face_selector_plane_missing_axis_rejected() -> None:
    with pytest.raises(ValidationError, match=r"target_face"):
        validate_params(hole_spec(), _hole_with_face({"surface": "plane"}), DEFS)


def test_face_selector_plane_empty_axis_rejected() -> None:
    with pytest.raises(ValidationError, match=r"target_face\.axis"):
        validate_params(hole_spec(), _hole_with_face({"surface": "plane", "axis": ""}), DEFS)


def test_face_selector_cylinder_without_or_empty_axis_valid_exactly_one_branch() -> None:
    # missing axis: valid
    r1 = validate_params(hole_spec(), _hole_with_face({"surface": "cylinder"}), DEFS)
    assert r1["target_face"] == {"surface": "cylinder"}
    # empty axis: valid (cylinder branch enum contains "")
    r2 = validate_params(hole_spec(), _hole_with_face({"surface": "cylinder", "axis": ""}), DEFS)
    assert r2["target_face"] == {"surface": "cylinder", "axis": ""}
    # both cases must match EXACTLY one branch (a both-branches match would
    # have raised oneOf "2 branches" above)
    r3 = validate_params(hole_spec(), _hole_with_face({"surface": "cylinder", "axis": "+Z"}), DEFS)
    assert r3["target_face"] == {"surface": "cylinder", "axis": "+Z"}


def test_face_selector_plane_unsigned_axis_rejected() -> None:
    with pytest.raises(ValidationError, match=r"target_face\.axis"):
        validate_params(hole_spec(), _hole_with_face({"surface": "plane", "axis": "Z"}), DEFS)


def test_schema_definitions_value_type_is_object() -> None:
    # guard: defs table values must be mappings (defensive against forged tables)
    bad_defs: Mapping[str, object] = {"Mode": "not-a-schema"}
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"mode": {"$ref": "#/$defs/Mode"}},
        "additionalProperties": False,
    }
    with pytest.raises(ValidationError, match="Mode"):
        validate_params(_spec_with(schema), {"mode": "new"}, bad_defs)


def test_boolean_type_accepts_only_bool() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"flag": {"type": "boolean"}},
        "additionalProperties": False,
    }
    assert validate_params(_spec_with(schema), {"flag": True}) == {"flag": True}
    for bad in (1, "true", None, 0.0):
        with pytest.raises(ValidationError, match="flag"):
            validate_params(_spec_with(schema), {"flag": bad})


def test_object_type_rejects_non_mapping() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"o": {"type": "object"}},
        "additionalProperties": False,
    }
    with pytest.raises(ValidationError, match="o"):
        validate_params(_spec_with(schema), {"o": [1]}, DEFS)


def test_exclusive_maximum() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"n": {"type": "number", "exclusiveMaximum": 360.0}},
        "additionalProperties": False,
    }
    assert validate_params(_spec_with(schema), {"n": 359.9}) == {"n": 359.9}
    with pytest.raises(ValidationError, match="exclusiveMaximum"):
        validate_params(_spec_with(schema), {"n": 360})


def test_array_of_scalars_items_validation() -> None:
    with pytest.raises(ValidationError, match=r"center\.1"):
        validate_params(cylinder_spec(), {"radius": 1, "height": 2, "center": [0, "x", 0]}, DEFS)


def test_deeply_nested_dotted_path_in_error() -> None:
    params: dict[str, object] = {
        "base_hole": {
            "target_face": {"surface": "plane", "axis": "+Z"},
            "position": {"kind": "center"},
            "diameter": 6,
            "depth": {"kind": "through_all"},
        },
        "pattern": {"kind": "polar", "radius": -5, "count": 4},
    }
    from tests.commands._fixtures import hole_pattern_spec

    with pytest.raises(ValidationError, match=r"pattern\.radius"):
        validate_params(hole_pattern_spec(), params, DEFS)


def test_validate_params_returns_plain_dict() -> None:
    result = validate_params(cylinder_spec(), {"radius": 1, "height": 2}, DEFS)
    assert isinstance(result, dict)
    assert type(result) is dict
    center = cast("list[object]", result["center"])
    assert type(center) is list
