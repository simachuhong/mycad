# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""feature.cylinder demo command tests: field-by-field deep equality against
a HAND-WRITTEN transcription of Appendix A.1 (reverse-recording from the
implementation is forbidden), plus the full pipeline through the demo
registry (register -> validate -> defaults filled).
"""

from __future__ import annotations

import dataclasses

from mycad.commands.demo import DEMO_SCHEMA_DEFS, cylinder_spec, demo_registry
from mycad.commands.validation import validate_params

#: Handwritten expectation (Appendix A.1 + A.0, transcribed by hand).
EXPECTED_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["radius", "height"],
    "additionalProperties": False,
    "properties": {
        "radius": {"$ref": "#/$defs/Positive"},
        "height": {"$ref": "#/$defs/Positive"},
        "center": {"$ref": "#/$defs/Center3"},
        "mode": {"$ref": "#/$defs/Mode"},
    },
}

EXPECTED_DEFS: dict[str, object] = {
    "Mode": {"type": "string", "enum": ["new", "add", "cut"], "default": "new"},
    "Center3": {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
        "default": [0.0, 0.0, 0.0],
    },
    "Positive": {"type": "number", "exclusiveMinimum": 0.0},
}


def test_demo_defs_match_handwritten_transcription() -> None:
    assert DEMO_SCHEMA_DEFS == EXPECTED_DEFS
    assert set(DEMO_SCHEMA_DEFS) >= {"Mode", "Center3", "Positive"}


def test_cylinder_spec_field_by_field_equality() -> None:
    spec = cylinder_spec()
    assert spec.id == "feature.cylinder"
    assert spec.version == 1
    assert spec.summary_en == "Create a cylinder"
    assert spec.label_zh == "圆柱体"
    assert spec.params_schema == EXPECTED_SCHEMA
    assert spec.cli.verb_aliases == ("cylinder",)
    assert spec.cli.positional == ()
    assert spec.undo_compensation == "history_replay"
    assert [f.name for f in dataclasses.fields(spec)] == [
        "id",
        "version",
        "summary_en",
        "label_zh",
        "params_schema",
        "cli",
        "undo_compensation",
    ]


def test_cylinder_spec_fresh_instance_each_call() -> None:
    assert cylinder_spec() is not cylinder_spec()
    assert cylinder_spec() == cylinder_spec()


def test_demo_registry_registers_exactly_one_command() -> None:
    registry = demo_registry()
    grouped = registry.list_by_category()
    assert set(grouped) == {"feature"}
    specs = grouped["feature"]
    assert len(specs) == 1
    assert specs[0].id == "feature.cylinder"
    assert registry.schema_defs == DEMO_SCHEMA_DEFS


def test_demo_pipeline_validates_and_fills_defaults() -> None:
    registry = demo_registry()
    spec = registry.get("feature.cylinder")
    result = validate_params(spec, {"radius": 40, "height": 8}, defs=registry.schema_defs)
    assert result == {
        "radius": 40,
        "height": 8,
        "center": [0.0, 0.0, 0.0],
        "mode": "new",
    }
