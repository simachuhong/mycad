# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Field-level lock of built-in CommandSpecs (Appendix A.1 plus releases)
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

#: Appendix A.1 ids followed by individually released P2 drawing/modeling commands.
EXPECTED_IDS: tuple[str, ...] = (
    "feature.box",
    "feature.cylinder",
    "feature.sphere",
    "feature.extrude",
    "feature.revolve",
    "feature.hole",
    "feature.hole_pattern",
    "modify.fillet",
    "modify.boolean_cut",
    "modify.boolean_intersect",
    "modify.boolean_bodies",
    "modify.body_transform",
    "modify.body_pattern",
    "modify.chamfer",
    "sketch.create",
    "sketch.constraint.add",
    "datum.coordinate_system.create",
    "datum.plane.create",
    "sketch.constraint.update",
    "sketch.revise",
    "drawing.sketch.revise",
    "drawing.layers.set",
    "drawing.sheet.create",
    "drawing.sheet.update",
    "drawing.sheet.delete",
    "drawing.view.create",
    "drawing.view.update",
    "drawing.view.delete",
    "drawing.annotation.create",
    "drawing.annotation.update",
    "drawing.annotation.delete",
    "drawing.note.create",
    "drawing.note.update",
    "drawing.note.delete",
    "reference.attach",
    "reference.update",
    "reference.detach",
)


def _spec(command_id: str, version: int = 1) -> CommandSpec:
    matches = [
        spec for spec in BUILTIN_COMMAND_SPECS if spec.id == command_id and spec.version == version
    ]
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
        "profile": {"$ref": "#/$defs/ExtrudeProfile"},
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
            "items": {
                "oneOf": [
                    {"$ref": "#/$defs/EdgeSelector"},
                    {"$ref": "#/$defs/InteractiveEdgeSelector"},
                ]
            },
            "minItems": 1,
        },
        "radius": {"$ref": "#/$defs/Positive"},
    },
    "required": ["edges", "radius"],
    "additionalProperties": False,
}

EXPECTED_CHAMFER_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "edges": {
            "type": "array",
            "items": {
                "oneOf": [
                    {"$ref": "#/$defs/EdgeSelector"},
                    {"$ref": "#/$defs/InteractiveEdgeSelector"},
                ]
            },
            "minItems": 1,
        },
        "distance": {"$ref": "#/$defs/Positive"},
    },
    "required": ["edges", "distance"],
    "additionalProperties": False,
}

EXPECTED_BOOLEAN_CUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"tool": {"$ref": "#/$defs/Tool"}},
    "required": ["tool"],
    "additionalProperties": False,
}

EXPECTED_BOOLEAN_INTERSECT_SCHEMA: dict[str, object] = {
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
    assert spec.summary_en == "Extrude a parametric profile or a selected planar face"
    assert spec.label_zh == "拉伸"
    assert spec.cli.verb_aliases == ("extrude",)
    assert spec.undo_compensation == "history_replay"
    assert spec.params_schema == EXPECTED_EXTRUDE_SCHEMA


def test_sketch_extrude_v2_is_additive_and_keeps_the_cli_entry() -> None:
    v1 = _spec("feature.extrude", 1)
    v2 = _spec("feature.extrude", 2)
    registry = _builtin_registry()

    assert v1.params_schema == EXPECTED_EXTRUDE_SCHEMA
    assert v2.cli.verb_aliases == ("extrude",)
    assert v2.params_schema["properties"] == {
        "profile": {"$ref": "#/$defs/SketchExtrudeProfile"},
        "distance": {"type": "number"},
        "mode": {"$ref": "#/$defs/Mode"},
    }
    v3_properties = cast(
        "dict[str, object]", _spec("feature.extrude", 3).params_schema["properties"]
    )
    assert v3_properties["extent_mode"] == {
        "type": "string",
        "enum": ["one_sided", "symmetric"],
        "default": "one_sided",
        "description": "symmetric uses distance as total depth, split equally across the sketch plane",
    }
    assert registry.versions("feature.extrude") == (1, 2, 3, 4, 5)
    assert registry.resolve_verb("extrude") == _spec("feature.extrude", 5)


def test_sketch_extrude_v3_adds_symmetric_extent_without_changing_v2() -> None:
    v2 = _spec("feature.extrude", 2)
    v3 = _spec("feature.extrude", 3)
    registry = _builtin_registry()
    sketch_params = {
        "profile": {
            "type": "sketch",
            "sketch_id": "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a",
        },
        "distance": 8.0,
        "mode": "new",
        "extent_mode": "symmetric",
    }

    assert v2.params_schema["properties"] == {
        "profile": {"$ref": "#/$defs/SketchExtrudeProfile"},
        "distance": {"type": "number"},
        "mode": {"$ref": "#/$defs/Mode"},
    }
    assert (
        validate_params(v3, sketch_params, defs=registry.schema_defs)["extent_mode"] == "symmetric"
    )
    assert (
        validate_params(
            v3,
            {"profile": sketch_params["profile"], "distance": 8.0},
            defs=registry.schema_defs,
        )["extent_mode"]
        == "one_sided"
    )
    with pytest.raises(ValidationError):
        validate_params(v2, sketch_params, defs=registry.schema_defs)


def test_sketch_extrude_v4_requires_a_planar_target_for_to_face() -> None:
    params = {
        "profile": {
            "type": "sketch",
            "sketch_id": "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a",
        },
        "mode": "new",
        "extent_mode": "to_face",
        "target_face": {
            "surface": "plane",
            "axis": "+Z",
            "center_mm": [0.0, 0.0, 25.0],
        },
    }

    validated = validate_params(_spec("feature.extrude", 4), params, defs=COMMAND_SCHEMA_DEFS)

    assert validated["extent_mode"] == "to_face"
    assert validated["target_face"] == params["target_face"]
    assert (
        validate_params(
            _spec("feature.extrude", 4),
            {key: value for key, value in params.items() if key != "mode"},
            defs=COMMAND_SCHEMA_DEFS,
        )["mode"]
        == "new"
    )
    with pytest.raises(ValidationError, match="oneOf"):
        validate_params(
            _spec("feature.extrude", 4),
            {key: value for key, value in params.items() if key != "target_face"},
            defs=COMMAND_SCHEMA_DEFS,
        )
    with pytest.raises(ValidationError, match="oneOf"):
        validate_params(
            _spec("feature.extrude", 4),
            {
                **params,
                "target_face": {
                    "surface": "cylinder",
                    "axis": "+Z",
                    "center_mm": [0.0, 0.0, 25.0],
                    "radius_mm": 5.0,
                },
            },
            defs=COMMAND_SCHEMA_DEFS,
        )


def test_sketch_revolve_v2_is_additive_and_keeps_the_cli_entry() -> None:
    v1 = _spec("feature.revolve", 1)
    v2 = _spec("feature.revolve", 2)
    registry = _builtin_registry()

    assert v1.version == 1
    assert v2.version == 2
    assert v2.cli.verb_aliases == ("revolve",)
    properties = cast("dict[str, object]", v2.params_schema["properties"])
    assert properties["profile"] == {"$ref": "#/$defs/SketchRevolveProfile"}
    assert registry.versions("feature.revolve") == (1, 2, 3, 4)
    resolved = registry.resolve_verb("revolve")
    assert resolved is not None and resolved.version == 4


def test_sketch_revolve_v3_adds_a_stable_construction_line_axis_reference() -> None:
    v2 = _spec("feature.revolve", 2)
    v3 = _spec("feature.revolve", 3)
    registry = _builtin_registry()
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    entity_id = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
    params = {
        "profile": {"type": "sketch", "sketch_id": sketch_id},
        "axis_reference": {
            "type": "sketch_line",
            "sketch_id": sketch_id,
            "entity_id": entity_id,
        },
        "angle_deg": 360.0,
        "mode": "new",
    }

    assert v2.params_schema == {
        "type": "object",
        "properties": {
            "profile": {"$ref": "#/$defs/SketchRevolveProfile"},
            "axis": {
                "oneOf": [
                    {"const": "X"},
                    {"const": "Y"},
                    {"const": "Z"},
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
    assert v3.version == 3
    assert (
        validate_params(v3, params, defs=registry.schema_defs)["axis_reference"]
        == params["axis_reference"]
    )
    with pytest.raises(ValidationError):
        validate_params(v3, {**params, "axis": "Z"}, defs=registry.schema_defs)
    with pytest.raises(ValidationError):
        validate_params(v2, params, defs=registry.schema_defs)
    assert registry.versions("feature.revolve") == (1, 2, 3, 4)
    assert registry.resolve_verb("revolve") == _spec("feature.revolve", 4)


def test_sketch_hole_v2_is_additive_and_keeps_the_cli_entry() -> None:
    v1 = _spec("feature.hole", 1)
    v2 = _spec("feature.hole", 2)
    registry = _builtin_registry()

    assert v1.version == 1
    assert v2.version == 2
    assert v2.cli.verb_aliases == ("hole",)
    assert v2.params_schema == {
        "oneOf": [
            {"$ref": "#/$defs/Hole"},
            {"$ref": "#/$defs/SketchHole"},
        ]
    }
    assert registry.versions("feature.hole") == (1, 2, 3)
    assert registry.resolve_verb("hole") == _spec("feature.hole", 3)


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


def test_chamfer_spec_fields() -> None:
    spec = _spec("modify.chamfer")
    assert spec.id == "modify.chamfer"
    assert spec.version == 1
    assert spec.summary_en == "Chamfer selected edges with equal setbacks"
    assert spec.label_zh == "倒角"
    assert spec.cli.verb_aliases == ("chamfer",)
    assert spec.undo_compensation == "history_replay"
    assert spec.params_schema == EXPECTED_CHAMFER_SCHEMA


def test_boolean_cut_spec_fields() -> None:
    spec = _spec("modify.boolean_cut")
    assert spec.id == "modify.boolean_cut"
    assert spec.version == 1
    assert spec.summary_en == "Subtract an inline tool solid"
    assert spec.label_zh == "差集"
    assert spec.cli.verb_aliases == ("cut",)
    assert spec.undo_compensation == "history_replay"
    assert spec.params_schema == EXPECTED_BOOLEAN_CUT_SCHEMA


def test_boolean_intersect_spec_fields() -> None:
    spec = _spec("modify.boolean_intersect")
    assert spec.id == "modify.boolean_intersect"
    assert spec.version == 1
    assert spec.summary_en == "Intersect the current model with an inline tool solid"
    assert spec.label_zh == "交集"
    assert spec.cli.verb_aliases == ("intersect",)
    assert spec.undo_compensation == "history_replay"
    assert spec.params_schema == EXPECTED_BOOLEAN_INTERSECT_SCHEMA


def test_body_boolean_and_transform_specs_use_replayable_body_locators() -> None:
    boolean = _spec("modify.boolean_bodies")
    transform = _spec("modify.body_transform")
    pattern = _spec("modify.body_pattern")
    assert boolean.min_archive_version == 2
    assert boolean.params_schema == {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["union", "difference", "intersection"],
            },
            "target_body": {"$ref": "#/$defs/BodySelector"},
            "tool_body": {"$ref": "#/$defs/BodySelector"},
            "keep_tool": {"type": "boolean", "default": False},
        },
        "required": ["operation", "target_body", "tool_body"],
        "additionalProperties": False,
    }
    assert transform.params_schema["properties"] == {
        "body": {"$ref": "#/$defs/BodySelector"},
        "transform": {"$ref": "#/$defs/BodyTransform"},
    }
    assert pattern.params_schema["properties"] == {
        "seed_body": {"$ref": "#/$defs/BodySelector"},
        "pattern": {"$ref": "#/$defs/BodyPattern"},
    }


def test_sketch_create_spec_is_versioned_and_requires_v2_persistence() -> None:
    spec = _spec("sketch.create", 1)

    assert spec.version == 1
    assert spec.min_archive_version == 2
    assert spec.label_zh == "创建草图"
    assert spec.cli.verb_aliases == ("sketch-create",)
    assert spec.params_schema["required"] == ["sketch_id", "frame", "entities"]


def test_sketch_point_requires_new_command_version() -> None:
    from mycad.core.sketch import PointEntity, Sketch, WorkPlaneFrame

    point = PointEntity("a1" * 16, (2, 3))
    sketch = Sketch("b2" * 16, WorkPlaneFrame.xy(), (point,))
    params = sketch.to_mapping(version=4)
    with pytest.raises(ValidationError):
        validate_params(_spec("sketch.create", 3), params, defs=COMMAND_SCHEMA_DEFS)
    assert (
        validate_params(_spec("sketch.create", 5), params, defs=COMMAND_SCHEMA_DEFS)["entities"]
        == params["entities"]
    )


def test_sketch_create_v2_schema_accepts_layered_sketch_and_rejects_missing_entity_layer() -> None:
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    layer = SketchLayer("OUTLINE", color_rgb=(20, 80, 160), linetype="DASHED")
    sketch = Sketch(
        "0a0a0a0a0a0a4a0a8a0a0a0a0a0a0a0a",
        WorkPlaneFrame.xy(),
        (
            LineEntity(
                "1b1b1b1b1b1b4b1b8b1b1b1b1b1b1b1b",
                (0.0, 0.0),
                (10.0, 0.0),
                layer_name="OUTLINE",
            ),
        ),
        layers=SketchLayerTable().add(layer),
    )
    spec = _spec("sketch.create", 2)

    validated = validate_params(spec, sketch.to_mapping(), defs=COMMAND_SCHEMA_DEFS)
    invalid = sketch.to_mapping()
    invalid_entities = cast("list[object]", invalid["entities"])
    invalid_entities[0] = {
        key: value
        for key, value in cast("dict[str, object]", invalid_entities[0]).items()
        if key != "layer_name"
    }
    validated_layers = cast("list[dict[str, object]]", validated["layers"])

    assert validated_layers[1]["name"] == "OUTLINE"
    with pytest.raises(ValidationError):
        validate_params(spec, invalid, defs=COMMAND_SCHEMA_DEFS)


def test_sketch_create_v2_schema_accepts_replayable_face_support() -> None:
    from mycad.core.sketch import LineEntity, Sketch, SketchSupportFace, WorkPlaneFrame

    sketch = Sketch(
        "0a0a0a0a0a0a4a0a8a0a0a0a0a0a0a0a",
        WorkPlaneFrame.xy(),
        (LineEntity("1b1b1b1b1b1b4b1b8b1b1b1b1b1b1b1b", (0.0, 0.0), (10.0, 0.0)),),
        support_face=SketchSupportFace((1.0, 2.0, 3.0), "+Z", 0),
    )

    validated = validate_params(
        _spec("sketch.create", 2), sketch.to_mapping(), defs=COMMAND_SCHEMA_DEFS
    )

    assert validated["support_face"] == {
        "surface": "plane",
        "center_mm": [1.0, 2.0, 3.0],
        "axis": "+Z",
        "rank": 0,
    }


def test_sketch_create_v3_schema_accepts_associated_dimensions() -> None:
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    sketch = Sketch(
        "0a0a0a0a0a0a4a0a8a0a0a0a0a0a0a0a",
        WorkPlaneFrame.xy(),
        (
            LineEntity(
                "1b1b1b1b1b1b4b1b8b1b1b1b1b1b1b1b",
                (0.0, 0.0),
                (10.0, 0.0),
            ),
        ),
        constraints=(
            SketchConstraint(
                "2c2c2c2c2c2c4c2c8c2c2c2c2c2c2c2c",
                "length",
                (SketchGeometryReference("1b1b1b1b1b1b4b1b8b1b1b1b1b1b1b1b", "geometry"),),
                value=10.0,
                unit="mm",
                driving=False,
                precision=3,
                scale=2.0,
            ),
        ),
    )

    validated = validate_params(
        _spec("sketch.create", 3), sketch.to_mapping(version=3), defs=COMMAND_SCHEMA_DEFS
    )

    assert validated["constraints"] == [sketch.constraints[0].to_mapping()]


def test_sketch_create_v3_schema_accepts_inferred_geometric_relations() -> None:
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    sketch = Sketch(
        "0a0a0a0a0a0a4a0a8a0a0a0a0a0a0a0a",
        WorkPlaneFrame.xy(),
        (
            LineEntity(
                "1b1b1b1b1b1b4b1b8b1b1b1b1b1b1b1b",
                (0.0, 0.0),
                (10.0, 0.0),
            ),
        ),
        constraints=(
            SketchConstraint(
                "2c2c2c2c2c2c4c2c8c2c2c2c2c2c2c2c",
                "horizontal",
                (SketchGeometryReference("1b1b1b1b1b1b4b1b8b1b1b1b1b1b1b1b", "geometry"),),
                source="inferred",
            ),
        ),
    )

    validated = validate_params(
        _spec("sketch.create", 3), sketch.to_mapping(version=3), defs=COMMAND_SCHEMA_DEFS
    )

    assert validated["constraints"] == [sketch.constraints[0].to_mapping()]


def test_sketch_constraint_command_is_versioned_and_replayable() -> None:
    spec = _spec("sketch.constraint.add")

    assert spec.version == 1
    assert spec.min_archive_version == 2
    assert spec.label_zh == "添加草图约束"
    assert spec.cli.verb_aliases == ()
    assert spec.undo_compensation == "history_replay"
    assert spec.params_schema["required"] == [
        "sketch_id",
        "base_state_sha256",
        "constraint",
        "solver_id",
        "solver_version",
        "degrees_of_freedom",
        "solution_entities",
    ]


def test_sketch_constraint_add_v2_accepts_formatting_and_v1_remains_frozen() -> None:
    params: dict[str, object] = {
        "sketch_id": "0a0a0a0a0a0a4a0a8a0a0a0a0a0a0a0a",
        "base_state_sha256": "0" * 64,
        "constraint": {
            "constraint_id": "2c2c2c2c2c2c4c2c8c2c2c2c2c2c2c2c",
            "kind": "length",
            "references": [
                {
                    "entity_id": "1b1b1b1b1b1b4b1b8b1b1b1b1b1b1b1b",
                    "kind": "geometry",
                }
            ],
            "value": 10.0,
            "unit": "mm",
            "driving": False,
            "source": "user",
            "precision": 3,
            "scale": 2.0,
        },
        "solver_id": "planegcs",
        "solver_version": "1.2.3",
        "degrees_of_freedom": 2,
        "solution_entities": [],
    }

    assert _spec("sketch.constraint.add", 2).version == 2
    validate_params(_spec("sketch.constraint.add", 2), params, defs=COMMAND_SCHEMA_DEFS)
    with pytest.raises(ValidationError):
        validate_params(_spec("sketch.constraint.add", 1), params, defs=COMMAND_SCHEMA_DEFS)
    normalized = validate_params(
        _spec("sketch.constraint.add", 3), params, defs=COMMAND_SCHEMA_DEFS
    )
    assert normalized["rebuild_consumers"] is True
    with pytest.raises(ValidationError):
        validate_params(
            _spec("sketch.constraint.add", 3),
            {**params, "rebuild_consumers": False},
            defs=COMMAND_SCHEMA_DEFS,
        )
    with pytest.raises(ValidationError):
        validate_params(_spec("sketch.constraint.add", 2), normalized, defs=COMMAND_SCHEMA_DEFS)


# ---------------------------------------------------------------------------
# registry assembly + catalog order
# ---------------------------------------------------------------------------


def test_registry_holds_the_appendix_a1_ids_and_released_p2_ids() -> None:
    registry = _builtin_registry()
    assert _registered_ids(registry) == sorted(EXPECTED_IDS)


def test_builtin_ids_follow_catalog_order() -> None:
    assert BUILTIN_COMMAND_IDS == EXPECTED_IDS
    assert tuple(dict.fromkeys(spec.id for spec in BUILTIN_COMMAND_SPECS)) == EXPECTED_IDS


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
    "shell",
    "union",
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


def test_datum_namespace_contains_only_adr_016_commands() -> None:
    ids = _registered_ids(_builtin_registry())
    assert {command_id for command_id in ids if command_id.startswith("datum.")} == {
        "datum.coordinate_system.create",
        "datum.plane.create",
    }


# ---------------------------------------------------------------------------
# AFFECTED_OBJECTS static shape (Appendix B.2) + PlannedCommand table gate
# ---------------------------------------------------------------------------


def test_affected_objects_static_shape() -> None:
    assert len(AFFECTED_OBJECTS) == 29
    ids = _registered_ids(_builtin_registry())
    # Legacy sketch/layer commands remain outside agent plans.
    assert set(AFFECTED_OBJECTS) == set(ids) - {
        "sketch.create",
        "sketch.constraint.add",
        "sketch.constraint.update",
        "sketch.revise",
        "drawing.sketch.revise",
        "drawing.layers.set",
        "datum.coordinate_system.create",
        "datum.plane.create",
    }
    assert len(set(AFFECTED_OBJECTS.values())) == 19
    assert set(AFFECTED_OBJECTS.values()) == {
        "box_body",
        "cylinder_body",
        "sphere_body",
        "extruded_body",
        "revolved_body",
        "hole",
        "hole_pattern",
        "edge",
        "chamfer_edge",
        "tool_body",
        "intersection_tool_body",
        "body_pair",
        "body_transform",
        "body_pattern",
        "drawing_sheet",
        "drawing_view",
        "drawing_annotation",
        "drawing_note",
        "document_reference",
    }


@pytest.mark.parametrize(
    "unknown_id",
    [
        "feature.sweep",
        "datum.xy",
        "",
        "feature.boxx",
        "sketch.create",
        "sketch.constraint.add",
        "sketch.constraint.update",
        "sketch.revise",
    ],
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


def test_chamfer_is_available_to_the_plan_confirmation_table() -> None:
    planned = PlannedCommand(
        id="modify.chamfer",
        version=1,
        params={"edges": [], "distance": 1.0},
        summary_en="Chamfer selected edges with equal setbacks",
        affected_object="chamfer_edge",
    )
    assert planned.id == "modify.chamfer"


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
    latest: dict[str, CommandSpec] = {}
    for spec in BUILTIN_COMMAND_SPECS:
        if spec.id not in latest or spec.version > latest[spec.id].version:
            latest[spec.id] = spec
    aliases = [alias for spec in latest.values() for alias in spec.cli.verb_aliases]
    assert len(aliases) == 27
    assert len(set(aliases)) == 27


def test_cut_verb_is_exclusive_to_boolean_cut() -> None:
    claimants = [spec.id for spec in BUILTIN_COMMAND_SPECS if "cut" in spec.cli.verb_aliases]
    assert claimants == ["modify.boolean_cut"]
