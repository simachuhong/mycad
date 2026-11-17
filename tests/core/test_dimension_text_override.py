# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A display override is separate from the measured or driving value."""

from dataclasses import replace
from typing import cast
from uuid import uuid4

import pytest

from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_dimension_text_override_roundtrip_keeps_value_and_legacy_mapping() -> None:
    ref = SketchGeometryReference(uuid4().hex, "geometry")
    dimension = SketchConstraint(uuid4().hex, "length", (ref,), 25, "mm")
    assert "text_override" not in dimension.to_mapping()
    decorated = replace(dimension, text_override="长 <> mm")
    assert decorated.value == 25
    assert decorated.to_mapping()["text_override"] == "长 <> mm"
    assert SketchConstraint.from_mapping(decorated.to_mapping()) == decorated
    assert SketchConstraint.from_mapping(dimension.to_mapping()) == dimension


@pytest.mark.parametrize("text", ["", "x" * 257, "bad\nline"])
def test_dimension_text_override_rejects_empty_long_or_multiline(text: str) -> None:
    ref = SketchGeometryReference(uuid4().hex, "geometry")
    with pytest.raises(ValueError):
        SketchConstraint(uuid4().hex, "length", (ref,), 25, "mm", text_override=text)


def test_geometric_relation_cannot_carry_dimension_text() -> None:
    ref = SketchGeometryReference(uuid4().hex, "geometry")
    with pytest.raises(ValueError):
        SketchConstraint(uuid4().hex, "horizontal", (ref,), text_override="<> mm")


def test_mapping_rejects_non_string_and_explicit_null_override() -> None:
    ref = SketchGeometryReference(uuid4().hex, "geometry")
    dimension = SketchConstraint(uuid4().hex, "length", (ref,), 25, "mm")
    for invalid in (None, 42, ["text"]):
        with pytest.raises(ValueError):
            SketchConstraint.from_mapping({**dimension.to_mapping(), "text_override": invalid})


@pytest.mark.parametrize(
    ("command", "version"),
    [
        ("sketch.create", 30),
        ("sketch.create", 31),
        ("sketch.constraint.add", 7),
        ("sketch.constraint.update", 5),
        ("sketch.revise", 7),
        ("drawing.sketch.revise", 48),
        ("drawing.sketch.revise", 49),
        ("drawing.tangency.add", 8),
    ],
)
def test_new_command_schema_includes_text_override(command: str, version: int) -> None:
    from mycad.builtin_commands import BUILTIN_COMMAND_SPECS

    spec = next(s for s in BUILTIN_COMMAND_SPECS if s.id == command and s.version == version)

    def constraints(value: object) -> list[dict[str, object]]:
        if isinstance(value, dict):
            mapping = cast("dict[str, object]", value)
            properties = mapping.get("properties")
            result = (
                [cast("dict[str, object]", properties)]
                if isinstance(properties, dict)
                and {"constraint_id", "kind", "references", "driving", "source"}
                <= cast("dict[str, object]", properties).keys()
                else []
            )
            return result + [item for child in mapping.values() for item in constraints(child)]
        if isinstance(value, list):
            return [item for child in cast("list[object]", value) for item in constraints(child)]
        return []

    found = constraints(spec.params_schema)
    assert found and all("text_override" in properties for properties in found)


def test_existing_create_schema_stays_frozen_and_new_schema_validates() -> None:
    from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
    from mycad.commands.validation import validate_params
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        text_override="宽 <> mm",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    old = next(s for s in BUILTIN_COMMAND_SPECS if s.id == "sketch.create" and s.version == 28)
    new = next(s for s in BUILTIN_COMMAND_SPECS if s.id == "sketch.create" and s.version == 30)
    with pytest.raises(ValidationError):
        validate_params(old, sketch.to_state_mapping(), defs=COMMAND_SCHEMA_DEFS)
    assert validate_params(new, sketch.to_state_mapping(), defs=COMMAND_SCHEMA_DEFS)
