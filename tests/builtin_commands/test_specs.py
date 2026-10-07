# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Field-level lock of the eight built-in CommandSpecs (plan Appendix A.1)
plus registry assembly, validate_params smoke tests and structural guards
(no P1/P2 id leaks, AFFECTED_OBJECTS shape, PlannedCommand table gate,
single COMMAND_SCHEMA_DEFS assignment site, CLI alias uniqueness).

Expected params_schema literals are handwritten from Appendix A.1 — NOT
imported from ``mycad.builtin_commands.specs`` — so a transcription error
on either side fails loudly.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import cast

import pytest

from mycad.builtin_commands import BUILTIN_COMMAND_IDS, BUILTIN_COMMAND_SPECS
from mycad.builtin_commands.defs import COMMAND_SCHEMA_DEFS
from mycad.commands.registry import CommandRegistry
from mycad.commands.spec import CommandSpec
from mycad.commands.validation import validate_params
from mycad.core.document import AFFECTED_OBJECTS, PlannedCommand
from mycad.core.exceptions import UnknownCommandError, ValidationError

REPO = Path(__file__).resolve().parents[2]

#: The eight Appendix A.1 ids in catalog order.
EXPECTED_IDS: tuple[str, ...] = (
    "feature.box",
    "feature.cylinder",
    "feature.extrude",
    "feature.revolve",
    "feature.hole",
    "feature.hole_pattern",
    "modify.fillet",
    "modify.boolean_cut",
)


def _spec(command_id: str) -> CommandSpec:
    matches = [spec for spec in BUILTIN_COMMAND_SPECS if spec.id == command_id]
    assert len(matches) == 1
    return matches[0]


def _builtin_registry() -> CommandRegistry:
    registry = CommandRegistry(schema_defs=COMMAND_SCHEMA_DEFS)
    for spec in BUILTIN_COMMAND_SPECS:
        registry.register(spec)
    return registry


def _registered_ids(registry: CommandRegistry) -> list[str]:
    return sorted(spec.id for group in registry.list_by_category().values() for spec in group)


EXPECTED_BOX_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "size_x": {"$ref": "#/$defs/Positive"},
        "size_y": {"$ref": "#/$defs/Positive"},
        "size_z": {"$ref": "#/$defs/Positive"},
        "center": {"$ref": "#/$defs/Center3"},
        "mode": {"$ref": "#/$defs/Mode"},
    },
    "required": ["size_x", "size_y", "size_z"],
    "additionalProperties": False,
}

EXPECTED_CYLINDER_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "radius": {"$ref": "#/$defs/Positive"},
        "height": {"$ref": "#/$defs/Positive"},
        "center": {"$ref": "#/$defs/Center3"},
        "mode": {"$ref": "#/$defs/Mode"},
    },
    "required": ["radius", "height"],
    "additionalProperties": False,
}

EXPECTED_EXTRUDE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "profile": {"$ref": "#/$defs/Profile"},
        "distance": {"type": "number"},
        "mode": {"$ref": "#/$defs/Mode"},
    },
    "required": ["profile", "distance"],
    "additionalProperties": False,
}

EXPECTED_REVOLVE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "profile": {"$ref": "#/$defs/Profile"},
        "axis": {
            "oneOf": [
                {"const": "X"},
                {"const": "Y"},
                {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            ]
        },
        "angle_deg": {
            "type": "number",
            "exclusiveMinimum": 0.0,
            "maximum": 360.0,
            "default": 360.0,
        },
        "mode": {"$ref": "#/$defs/Mode"},
    },
    "required": ["profile", "axis"],
    "additionalProperties": False,
}

EXPECTED_HOLE_PATTERN_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "base_hole": {"$ref": "#/$defs/Hole"},
        "pattern": {"$ref": "#/$defs/Pattern"},
    },
    "required": ["base_hole", "pattern"],
    "additionalProperties": False,
}

EXPECTED_FILLET_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "edges": {
            "type": "array",
            "items": {"$ref": "#/$defs/EdgeSelector"},
            "minItems": 1,
        },
        "radius": {"$ref": "#/$defs/Positive"},
    },
    "required": ["edges", "radius"],
    "additionalProperties": False,
}

EXPECTED_BOOLEAN_CUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"tool": {"$ref": "#/$defs/Tool"}},
    "required": ["tool"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# per-spec field locks (Appendix A.1, verbatim strings)
# ---------------------------------------------------------------------------


def test_box_spec_fields() -> None:
    spec = _spec("feature.box")
    assert spec.id == "feature.box"
    assert spec.version == 1
    assert spec.summary_en == "Create a rectangular box"
    assert spec.label_zh == "长方体"
    assert spec.cli.verb_aliases == ("box",)
    assert spec.undo_compensation == "history_replay"
    assert spec.params_schema == EXPECTED_BOX_SCHEMA


def test_cylinder_spec_fields() -> None:
    spec = _spec("feature.cylinder")
    assert spec.id == "feature.cylinder"
    assert spec.version == 1
    assert spec.summary_en == "Create a cylinder"
    assert spec.label_zh == "圆柱体"
    assert spec.cli.verb_aliases == ("cylinder",)
    assert spec.undo_compensation == "history_replay"
    assert spec.params_schema == EXPECTED_CYLINDER_SCHEMA


def test_extrude_spec_fields() -> None:
    spec = _spec("feature.extrude")
    assert spec.id == "feature.extrude"
    assert spec.version == 1
    assert spec.summary_en == "Extrude a parametric profile"
    assert spec.label_zh == "拉伸"
    assert spec.cli.verb_aliases == ("extrude",)
    assert spec.undo_compensation == "history_replay"
    assert spec.params_schema == EXPECTED_EXTRUDE_SCHEMA


def test_revolve_spec_fields() -> None:
    spec = _spec("feature.revolve")
    assert spec.id == "feature.revolve"
    assert spec.version == 1
    assert spec.summary_en == "Revolve a parametric profile"
    assert spec.label_zh == "旋转"
    assert spec.cli.verb_aliases == ("revolve",)
    assert spec.undo_compensation == "history_replay"
    assert spec.params_schema == EXPECTED_REVOLVE_SCHEMA


def test_hole_spec_fields() -> None:
    spec = _spec("feature.hole")
    assert spec.id == "feature.hole"
    assert spec.version == 1
    assert spec.summary_en == "Drill a predicate-located hole"
    assert spec.label_zh == "孔"
    assert spec.cli.verb_aliases == ("hole",)
    assert spec.undo_compensation == "history_replay"
    # #round11-3: root-level $ref, no type/object wrapper.
    assert spec.params_schema == {"$ref": "#/$defs/Hole"}


def test_hole_pattern_spec_fields() -> None:
    spec = _spec("feature.hole_pattern")
    assert spec.id == "feature.hole_pattern"
    assert spec.version == 1
    assert spec.summary_en == "Pattern a predicate-located hole"
    assert spec.label_zh == "孔阵列"
    assert spec.cli.verb_aliases == ("hole-pattern",)
    assert spec.undo_compensation == "history_replay"
    assert spec.params_schema == EXPECTED_HOLE_PATTERN_SCHEMA


def test_fillet_spec_fields() -> None:
    spec = _spec("modify.fillet")
    assert spec.id == "modify.fillet"
    assert spec.version == 1
    assert spec.summary_en == "Fillet selected edges"
    assert spec.label_zh == "圆角"
    assert spec.cli.verb_aliases == ("fillet",)
    assert spec.undo_compensation == "history_replay"
    assert spec.params_schema == EXPECTED_FILLET_SCHEMA


def test_boolean_cut_spec_fields() -> None:
    spec = _spec("modify.boolean_cut")
    assert spec.id == "modify.boolean_cut"
    assert spec.version == 1
    assert spec.summary_en == "Subtract an inline tool solid"
    assert spec.label_zh == "差集"
    assert spec.cli.verb_aliases == ("cut",)
    assert spec.undo_compensation == "history_replay"
    assert spec.params_schema == EXPECTED_BOOLEAN_CUT_SCHEMA


# ---------------------------------------------------------------------------
# registry assembly + catalog order
# ---------------------------------------------------------------------------


def test_registry_holds_exactly_the_eight_appendix_a1_ids() -> None:
    registry = _builtin_registry()
    assert _registered_ids(registry) == sorted(EXPECTED_IDS)


def test_builtin_ids_follow_catalog_order() -> None:
    assert BUILTIN_COMMAND_IDS == EXPECTED_IDS
    assert tuple(spec.id for spec in BUILTIN_COMMAND_SPECS) == EXPECTED_IDS


# ---------------------------------------------------------------------------
# validate_params smoke tests (defs table injected)
# ---------------------------------------------------------------------------


def test_validate_params_box_default_filling() -> None:
    spec = _spec("feature.box")
    result = validate_params(
        spec, {"size_x": 10, "size_y": 20, "size_z": 30}, defs=COMMAND_SCHEMA_DEFS
    )
    assert result["center"] == [0.0, 0.0, 0.0]
    assert result["mode"] == "new"


def test_validate_params_box_negative_size_rejected() -> None:
    spec = _spec("feature.box")
    with pytest.raises(ValidationError):
        validate_params(spec, {"size_x": -1, "size_y": 20, "size_z": 30}, defs=COMMAND_SCHEMA_DEFS)


def test_validate_params_hole_via_root_ref() -> None:
    spec = _spec("feature.hole")
    result = validate_params(
        spec,
        {
            "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
            "position": {"kind": "center"},
            "diameter": 20.0,
            "depth": {"kind": "through_all"},
        },
        defs=COMMAND_SCHEMA_DEFS,
    )
    assert set(result) == {"target_face", "position", "diameter", "depth"}


def test_validate_params_hole_pattern_polar_with_default() -> None:
    spec = _spec("feature.hole_pattern")
    result = validate_params(
        spec,
        {
            "base_hole": {
                "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
                "position": {"kind": "center"},
                "diameter": 6.0,
                "depth": {"kind": "through_all"},
            },
            "pattern": {"kind": "polar", "radius": 30.0, "count": 6},
        },
        defs=COMMAND_SCHEMA_DEFS,
    )
    pattern = cast("dict[str, object]", result["pattern"])
    assert pattern["start_angle_deg"] == 0.0


def test_validate_params_pattern_linear_rejected() -> None:
    spec = _spec("feature.hole_pattern")
    with pytest.raises(ValidationError):
        validate_params(
            spec,
            {
                "base_hole": {
                    "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
                    "position": {"kind": "center"},
                    "diameter": 6.0,
                    "depth": {"kind": "through_all"},
                },
                "pattern": {"kind": "linear", "radius": 30.0, "count": 6},
            },
            defs=COMMAND_SCHEMA_DEFS,
        )


# ---------------------------------------------------------------------------
# P1/P2 leak guards (ADR-003 namespace reservation)
# ---------------------------------------------------------------------------

P1_P2_LEAKS: tuple[str, ...] = (
    "chamfer",
    "shell",
    "union",
    "intersect",
    "pattern_linear",
    "mirror",
    "draft",
    "sweep",
)


@pytest.mark.parametrize("leak", P1_P2_LEAKS)
def test_no_p1_p2_command_id_leak(leak: str) -> None:
    ids = _registered_ids(_builtin_registry())
    assert leak not in ids
    assert all(leak not in command_id.split(".") for command_id in ids)


def test_no_datum_namespace_leak() -> None:
    ids = _registered_ids(_builtin_registry())
    assert not any(command_id.startswith("datum.") for command_id in ids)


# ---------------------------------------------------------------------------
# AFFECTED_OBJECTS static shape (Appendix B.2) + PlannedCommand table gate
# ---------------------------------------------------------------------------


def test_affected_objects_static_shape() -> None:
    assert len(AFFECTED_OBJECTS) == 8
    ids = _registered_ids(_builtin_registry())
    assert set(AFFECTED_OBJECTS) == set(ids)
    assert len(set(AFFECTED_OBJECTS.values())) == 8
    assert set(AFFECTED_OBJECTS.values()) == {
        "box_body",
        "cylinder_body",
        "extruded_body",
        "revolved_body",
        "hole",
        "hole_pattern",
        "edge",
        "tool_body",
    }


@pytest.mark.parametrize(
    "unknown_id",
    ["feature.sweep", "modify.chamfer", "datum.xy", "", "feature.boxx"],
)
def test_planned_command_rejects_out_of_table_ids(unknown_id: str) -> None:
    with pytest.raises(UnknownCommandError):
        PlannedCommand(
            id=unknown_id,
            version=1,
            params={},
            summary_en="",
            affected_object="box_body",
        )


# ---------------------------------------------------------------------------
# single COMMAND_SCHEMA_DEFS assignment site (#round9-7) + CLI alias rules
# ---------------------------------------------------------------------------


def test_command_schema_defs_single_assignment_site() -> None:
    """Exactly one assignment to COMMAND_SCHEMA_DEFS in all of src/mycad.

    Covers both ast.Assign and ast.AnnAssign (the formal table uses the
    annotated form pinned by the T7a task spec, which parses as AnnAssign).
    """
    hits: list[str] = []
    for path in sorted((REPO / "src" / "mycad").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            target: ast.expr | None = None
            if isinstance(node, ast.Assign):
                target = node.targets[0]
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                target = node.target
            if isinstance(target, ast.Name) and target.id == "COMMAND_SCHEMA_DEFS":
                hits.append(path.relative_to(REPO).as_posix())
    assert hits == ["src/mycad/builtin_commands/defs.py"]


def test_cli_aliases_are_pairwise_distinct() -> None:
    aliases = [alias for spec in BUILTIN_COMMAND_SPECS for alias in spec.cli.verb_aliases]
    assert len(aliases) == 8
    assert len(set(aliases)) == 8


def test_cut_verb_is_exclusive_to_boolean_cut() -> None:
    claimants = [spec.id for spec in BUILTIN_COMMAND_SPECS if "cut" in spec.cli.verb_aliases]
    assert claimants == ["modify.boolean_cut"]
