# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""grammar tests: bidirectional parse_line/to_cli, the four value lexemes
(including bare identifiers), flat dotted keys, bracket scalar arrays,
schema-declaration key order, explicit defaults, integer-valued float
serialization, and the three mutually exclusive error layers.
"""

from __future__ import annotations

from typing import cast

import pytest

import mycad.commands.grammar as grammar_module
from mycad.commands.grammar import parse_line, to_cli
from mycad.commands.registry import CommandRegistry
from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.commands.validation import normalize_params, validate_params
from mycad.core.exceptions import (
    CliSyntaxError,
    UnknownCommandError,
    ValidationError,
)
from tests.commands._fixtures import synthetic_registry


def _lex_registry() -> CommandRegistry:
    """Registry with a string/bool/int scratch command for lexer tests."""
    registry = CommandRegistry()
    registry.register(
        CommandSpec(
            id="test.lex",
            version=1,
            summary_en="lexer scratch",
            label_zh="词法",
            params_schema={
                "type": "object",
                "properties": {
                    "flag": {"type": "boolean"},
                    "n": {"type": "integer"},
                    "s": {"type": "string", "enum": ["true", "false"]},
                    "label": {"type": "string"},
                },
                "additionalProperties": False,
            },
            cli=CliSyntax(verb_aliases=("syn",)),
        )
    )
    return registry


def _pipeline(registry: CommandRegistry, line: str) -> tuple[str, dict[str, object]]:
    command_id, params = parse_line(line, registry)
    spec = registry.get(command_id)
    return command_id, normalize_params(validate_params(spec, params, registry.schema_defs))


# ---------------------------------------------------------------------------
# docstring examples (>= 6, each with a parse -> to_cli -> parse roundtrip)
# ---------------------------------------------------------------------------

EXAMPLE_2 = (
    "hole target_face.surface=plane target_face.axis=+Z target_face.rank=0 "
    "position.kind=center diameter=20 depth.kind=through_all"
)
EXAMPLE_4 = (
    "hole-pattern base_hole.target_face.surface=plane base_hole.target_face.axis=+Z "
    "base_hole.target_face.rank=0 base_hole.position.kind=center base_hole.diameter=6 "
    "base_hole.depth.kind=through_all pattern.kind=polar pattern.radius=25 "
    "pattern.count=4 pattern.start_angle_deg=0"
)

#: (example line, command id, canonical to_cli line with ALL defaults explicit)
DOCSTRING_EXAMPLES: list[tuple[str, str, str]] = [
    (
        "cylinder radius=40 height=8 mode=new",
        "feature.cylinder",
        "cylinder radius=40 height=8 center=[0,0,0] mode=new",
    ),
    (EXAMPLE_2, "feature.hole", EXAMPLE_2),
    (
        "fillet edges.0.parent_faces.0.surface=cylinder edges.0.curve=circle radius=2",
        "modify.fillet",
        "fillet edges.0.parent_faces.0.surface=cylinder edges.0.curve=circle radius=2",
    ),
    (EXAMPLE_4, "feature.hole_pattern", EXAMPLE_4),
    (
        "extrude profile.type=circle profile.radius=30 distance=10",
        "feature.extrude",
        "extrude profile.type=circle profile.radius=30 profile.center=[0,0] distance=10 mode=new",
    ),
    (
        "box size_x=10 size_y=10 size_z=10 center=[1,2,3]",
        "feature.box",
        "box size_x=10 size_y=10 size_z=10 center=[1,2,3] mode=new",
    ),
    (
        "cut tool.type=box tool.size_x=5 tool.size_y=5 tool.size_z=5 tool.center=[0,0,-5]",
        "modify.boolean_cut",
        "cut tool.type=box tool.size_x=5 tool.size_y=5 tool.size_z=5 tool.center=[0,0,-5]",
    ),
]


def test_grammar_docstring_contains_the_six_mandated_examples() -> None:
    doc = grammar_module.__doc__ or ""
    for example_line, _, _ in DOCSTRING_EXAMPLES[:6]:
        assert example_line in doc, f"missing docstring example: {example_line}"


@pytest.mark.parametrize(("line", "command_id", "canonical"), DOCSTRING_EXAMPLES)
def test_docstring_examples_roundtrip(line: str, command_id: str, canonical: str) -> None:
    registry = synthetic_registry()
    parsed_id, params = _pipeline(registry, line)
    assert parsed_id == command_id
    assert to_cli(command_id, params, registry) == canonical
    assert parse_line(canonical, registry) == (command_id, params)


# ---------------------------------------------------------------------------
# roundtrip property over 20+ fixed and varied param sets
# ---------------------------------------------------------------------------

ROUNDTRIP_CASES: list[tuple[str, dict[str, object]]] = [
    ("feature.cylinder", {"radius": 40, "height": 8}),
    ("feature.cylinder", {"radius": 2.5, "height": 20, "mode": "cut"}),
    ("feature.cylinder", {"radius": 40, "height": 8, "center": [1.5, -2, 3.25]}),
    ("feature.cylinder", {"radius": 40, "height": 8, "center": [0, 0, 0], "mode": "new"}),
    ("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10}),
    ("feature.box", {"size_x": 0.001, "size_y": 25.0, "size_z": 100, "center": [-1, 0, 1]}),
    ("feature.extrude", {"profile": {"type": "circle", "radius": 30}, "distance": 10}),
    (
        "feature.extrude",
        {"profile": {"type": "rect", "width": 10, "height": 5}, "distance": -3},
    ),
    (
        "feature.extrude",
        {
            "profile": {"type": "circle", "radius": 7.5, "center": [5.5, 6.5]},
            "distance": 0.5,
            "mode": "add",
        },
    ),
    ("feature.revolve", {"profile": {"type": "circle", "radius": 10}, "axis": "X"}),
    (
        "feature.revolve",
        {
            "profile": {"type": "rect", "width": 4, "height": 8},
            "axis": "Y",
            "angle_deg": 180.5,
        },
    ),
    (
        "feature.revolve",
        {"profile": {"type": "circle", "radius": 3}, "axis": [0, 0, 1], "angle_deg": 90},
    ),
    (
        "feature.revolve",
        {
            "profile": {"type": "circle", "radius": 3},
            "axis": [1, 1, 1],
            "angle_deg": 270,
            "mode": "cut",
        },
    ),
    (
        "feature.hole",
        {
            "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
            "position": {"kind": "center"},
            "diameter": 20,
            "depth": {"kind": "through_all"},
        },
    ),
    (
        "feature.hole",
        {
            "target_face": {"surface": "cylinder", "axis": ""},
            "position": {"kind": "center"},
            "diameter": 6,
            "depth": {"kind": "through_all"},
        },
    ),
    (
        "feature.hole",
        {
            "target_face": {"surface": "plane", "axis": "-Y"},
            "position": {"kind": "center"},
            "diameter": 8,
            "depth": {"kind": "blind", "value": 5.5},
        },
    ),
    (
        "feature.hole",
        {
            "target_face": {"surface": "cylinder", "axis": "+Z", "rank": 2},
            "position": {"kind": "center"},
            "diameter": 10,
            "depth": {"kind": "blind", "value": 3},
        },
    ),
    (
        "feature.hole_pattern",
        {
            "base_hole": {
                "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
                "position": {"kind": "center"},
                "diameter": 6,
                "depth": {"kind": "through_all"},
            },
            "pattern": {
                "kind": "polar",
                "radius": 25,
                "count": 4,
                "start_angle_deg": 0.0,
            },
        },
    ),
    (
        "feature.hole_pattern",
        {
            "base_hole": {
                "target_face": {"surface": "cylinder", "axis": ""},
                "position": {"kind": "center"},
                "diameter": 2,
                "depth": {"kind": "through_all"},
            },
            "pattern": {
                "kind": "polar",
                "radius": 10,
                "count": 2,
                "start_angle_deg": 12.75,
            },
        },
    ),
    (
        "modify.fillet",
        {"edges": [{"parent_faces": [{"surface": "plane", "axis": "+Z", "rank": 1}]}], "radius": 2},
    ),
    (
        "modify.fillet",
        {
            "edges": [
                {"parent_faces": [{"surface": "cylinder", "axis": ""}], "curve": ""},
                {"parent_faces": [{"surface": "plane", "axis": "-X"}], "curve": "line"},
            ],
            "radius": 1.5,
        },
    ),
    (
        "modify.boolean_cut",
        {"tool": {"type": "box", "size_x": 5, "size_y": 5, "size_z": 5, "center": [0, 0, -5]}},
    ),
    ("modify.boolean_cut", {"tool": {"type": "cylinder", "radius": 2, "height": 3}}),
]


@pytest.mark.parametrize(("command_id", "raw_params"), ROUNDTRIP_CASES)
def test_roundtrip_property(command_id: str, raw_params: dict[str, object]) -> None:
    registry = synthetic_registry()
    spec = registry.get(command_id)
    canonical = normalize_params(validate_params(spec, raw_params, registry.schema_defs))
    line = to_cli(command_id, canonical, registry)
    assert parse_line(line, registry) == (command_id, canonical)


def test_roundtrip_case_count_is_at_least_20() -> None:
    assert len(ROUNDTRIP_CASES) >= 20


# ---------------------------------------------------------------------------
# bare-identifier lexeme (matrix items 1-5)
# ---------------------------------------------------------------------------


def test_bare_tokens_parse_as_strings_not_numbers_or_bools() -> None:
    registry = synthetic_registry()
    _, params = parse_line("cylinder radius=1 height=2 mode=new", registry)
    assert params["mode"] == "new" and isinstance(params["mode"], str)
    _, params = parse_line(
        "hole target_face.surface=plane target_face.axis=-Z "
        "position.kind=center diameter=3 depth.kind=through_all",
        registry,
    )
    target = cast("dict[str, object]", params["target_face"])
    assert target["axis"] == "-Z" and isinstance(target["axis"], str)
    assert target["surface"] == "plane" and isinstance(target["surface"], str)
    depth = cast("dict[str, object]", params["depth"])
    assert depth["kind"] == "through_all" and isinstance(depth["kind"], str)
    _, params = parse_line("extrude profile.type=circle profile.radius=30 distance=10", registry)
    profile = cast("dict[str, object]", params["profile"])
    assert profile["type"] == "circle" and isinstance(profile["type"], str)


def test_bare_invalid_enum_is_semantic_not_lexical() -> None:
    registry = synthetic_registry()
    # parse_line itself must succeed: "banana" is a legal bare token
    command_id, params = parse_line("cylinder radius=1 height=2 mode=banana", registry)
    assert command_id == "feature.cylinder"
    assert params["mode"] == "banana"
    # the enum rejection happens at the semantic (validator) layer
    spec = registry.get(command_id)
    with pytest.raises(ValidationError, match="mode"):
        validate_params(spec, params, registry.schema_defs)


def test_quoted_value_with_space_parses_and_unquoted_fails_lexically() -> None:
    registry = _lex_registry()
    _, params = parse_line(r'syn label="a b"', registry)
    assert params == {"label": "a b"}
    with pytest.raises(CliSyntaxError):
        parse_line("syn label=a b", registry)


def test_number_and_bool_shapes_vs_schema_string_enum() -> None:
    registry = _lex_registry()
    assert parse_line("syn flag=true", registry)[1] == {"flag": True}
    assert parse_line("syn n=3", registry)[1] == {"n": 3}
    # s is declared as a string enum: the true-shaped token stays a string
    assert parse_line("syn s=true", registry)[1] == {"s": "true"}


def test_bare_signed_token_roundtrip_keeps_leading_sign() -> None:
    registry = synthetic_registry()
    _, params = _pipeline(
        registry,
        "hole target_face.surface=plane target_face.axis=+Z "
        "position.kind=center diameter=3 depth.kind=through_all",
    )
    line = to_cli("feature.hole", params, registry)
    assert "target_face.axis=+Z" in line
    assert parse_line(line, registry)[1] == params


# ---------------------------------------------------------------------------
# to_cli serialization rules
# ---------------------------------------------------------------------------


def test_to_cli_key_order_follows_schema_declaration_order() -> None:
    registry = synthetic_registry()
    scrambled: dict[str, object] = {
        "mode": "add",
        "center": [1, 2, 3],
        "height": 8,
        "radius": 40,
    }
    line = to_cli("feature.cylinder", scrambled, registry)
    assert line == "cylinder radius=40 height=8 center=[1,2,3] mode=add"


def test_to_cli_integer_valued_floats_lose_the_decimal_point() -> None:
    registry = synthetic_registry()
    params: dict[str, object] = {
        "radius": 25.0,
        "height": 8,
        "center": [0.5, 25.0, 0.0],
        "mode": "new",
    }
    line = to_cli("feature.cylinder", params, registry)
    assert line == "cylinder radius=25 height=8 center=[0.5,25,0] mode=new"


def test_to_cli_defaults_are_always_explicit_no_compact_form() -> None:
    registry = synthetic_registry()
    line = to_cli(
        "feature.cylinder",
        {"radius": 40, "height": 8, "center": [0, 0, 0], "mode": "new"},
        registry,
    )
    assert "center=[0,0,0]" in line
    assert "mode=new" in line


def test_to_cli_omits_none_valued_keys() -> None:
    registry = synthetic_registry()
    params: dict[str, object] = {
        "target_face": {"surface": "cylinder", "axis": None},
        "position": {"kind": "center"},
        "diameter": 6,
        "depth": {"kind": "through_all"},
    }
    line = to_cli("feature.hole", params, registry)
    assert "axis" not in line
    assert "target_face.surface=cylinder" in line


def test_to_cli_quotes_strings_that_are_not_bare_tokens() -> None:
    registry = _lex_registry()
    line = to_cli("test.lex", {"label": "needs quoting"}, registry)
    assert line == 'syn label="needs quoting"'
    assert parse_line(line, registry)[1] == {"label": "needs quoting"}


def test_to_cli_escapes_quotes_and_backslashes() -> None:
    registry = _lex_registry()
    params: dict[str, object] = {"label": 'a"b\\c'}
    line = to_cli("test.lex", params, registry)
    assert line == 'syn label="a\\"b\\\\c"'
    assert parse_line(line, registry)[1] == params


def test_to_cli_unknown_command_raises() -> None:
    registry = synthetic_registry()
    with pytest.raises(UnknownCommandError):
        to_cli("feature.nope", {}, registry)


def test_to_cli_object_arrays_use_flat_index_keys() -> None:
    registry = synthetic_registry()
    params: dict[str, object] = {
        "edges": [
            {"parent_faces": [{"surface": "cylinder"}], "curve": "circle"},
            {"parent_faces": [{"surface": "plane", "axis": "-X", "rank": 4}]},
        ],
        "radius": 2,
    }
    line = to_cli("modify.fillet", params, registry)
    assert line == (
        "fillet edges.0.parent_faces.0.surface=cylinder edges.0.curve=circle "
        "edges.1.parent_faces.0.surface=plane edges.1.parent_faces.0.axis=-X "
        "edges.1.parent_faces.0.rank=4 radius=2"
    )


# ---------------------------------------------------------------------------
# three error layers, mutually exclusive
# ---------------------------------------------------------------------------


def test_layer1_unclosed_quote_is_clisyntax_error() -> None:
    registry = synthetic_registry()
    with pytest.raises(CliSyntaxError, match="unclosed"):
        parse_line('cylinder radius=40 height="8', registry)


def test_layer1_unclosed_quote_never_raises_unknown_command() -> None:
    # even with an unknown verb, the lexical layer fires first
    registry = synthetic_registry()
    with pytest.raises(CliSyntaxError):
        parse_line('cylnder radius="4 height=8', registry)


def test_layer1_bare_equals_is_clisyntax_error() -> None:
    registry = synthetic_registry()
    with pytest.raises(CliSyntaxError):
        parse_line("cylinder =", registry)
    with pytest.raises(CliSyntaxError):
        parse_line("cylinder radius=", registry)


def test_layer1_token_without_key_value_form_is_clisyntax_error() -> None:
    registry = synthetic_registry()
    with pytest.raises(CliSyntaxError):
        parse_line("cylinder junk radius=40 height=8", registry)


def test_layer1_unclosed_scalar_array_bracket() -> None:
    registry = synthetic_registry()
    with pytest.raises(CliSyntaxError, match="bracket"):
        parse_line("cylinder radius=40 height=8 center=[0,0", registry)
    with pytest.raises(CliSyntaxError, match="bracket"):
        parse_line("cylinder radius=40 height=8 center=[0, 0, 0]", registry)


def test_layer1_number_literal_required_for_number_key() -> None:
    registry = synthetic_registry()
    with pytest.raises(CliSyntaxError, match="abc"):
        parse_line("cylinder radius=abc height=8", registry)


def test_layer2_unknown_verb_with_suggestion() -> None:
    registry = synthetic_registry()
    with pytest.raises(UnknownCommandError) as exc_info:
        parse_line("cylnder radius=4 height=8", registry)
    assert exc_info.value.identifier == "cylnder"
    assert "cylinder" in str(exc_info.value)


def test_layer2_completely_unknown_verb() -> None:
    registry = synthetic_registry()
    with pytest.raises(UnknownCommandError) as exc_info:
        parse_line("bogus x=1", registry)
    assert exc_info.value.identifier == "bogus"


def test_layer3_unknown_key_is_validation_error_not_clisyntax() -> None:
    registry = synthetic_registry()
    command_id, params = parse_line("cylinder radius=1 height=2 extra=1", registry)
    assert command_id == "feature.cylinder"
    spec = registry.get(command_id)
    with pytest.raises(ValidationError, match="extra"):
        validate_params(spec, params, registry.schema_defs)


def test_layer3_negative_radius_is_validation_error() -> None:
    registry = synthetic_registry()
    command_id, params = parse_line("cylinder radius=-1 height=8", registry)
    assert params["radius"] == -1  # lexically a legal integer
    spec = registry.get(command_id)
    with pytest.raises(ValidationError, match="exclusiveMinimum"):
        validate_params(spec, params, registry.schema_defs)


def test_layer3_noncontiguous_array_indices_are_lexical() -> None:
    registry = synthetic_registry()
    with pytest.raises(CliSyntaxError):
        parse_line(
            "fillet edges.0.parent_faces.0.surface=cylinder "
            "edges.2.parent_faces.0.surface=cylinder radius=2",
            registry,
        )


# ---------------------------------------------------------------------------
# verb semantics / misc
# ---------------------------------------------------------------------------


def test_cut_verb_maps_only_to_modify_boolean_cut() -> None:
    registry = synthetic_registry()
    command_id, params = parse_line("cut tool.type=cylinder tool.radius=2 tool.height=3", registry)
    assert command_id == "modify.boolean_cut"
    tool = cast("dict[str, object]", params["tool"])
    assert tool["type"] == "cylinder"


def test_feature_subtraction_is_mode_cut_key_value() -> None:
    registry = synthetic_registry()
    command_id, params = parse_line("cylinder radius=2 height=20 mode=cut", registry)
    assert command_id == "feature.cylinder"
    assert params["mode"] == "cut"


def test_key_splits_at_first_equals() -> None:
    registry = _lex_registry()
    _, params = parse_line('syn label="a=b"', registry)
    assert params == {"label": "a=b"}


def test_empty_and_comment_lines_are_rejected_by_parse_line() -> None:
    # script mode (the T10 batch reader) skips these before calling parse_line
    registry = synthetic_registry()
    with pytest.raises(CliSyntaxError):
        parse_line("", registry)
    with pytest.raises(CliSyntaxError):
        parse_line("   ", registry)
    with pytest.raises(CliSyntaxError):
        parse_line("# a comment line", registry)


def test_registry_must_be_injected_no_module_verb_table() -> None:
    # a fresh empty registry knows no verbs
    with pytest.raises(UnknownCommandError):
        parse_line("cylinder radius=1 height=2", CommandRegistry())


def test_parse_line_returns_plain_nested_dicts_and_lists() -> None:
    registry = synthetic_registry()
    _, params = parse_line(
        "fillet edges.0.parent_faces.0.surface=cylinder edges.0.curve=circle radius=2",
        registry,
    )
    assert isinstance(params["edges"], list)
    edges = cast("list[object]", params["edges"])
    assert isinstance(edges[0], dict)
