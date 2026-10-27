# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral constraint records use stable entity references and explicit units."""

from __future__ import annotations

import pytest

from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import (
    ConstraintKind,
    ConstraintUnit,
    SketchConstraint,
    SketchGeometryReference,
)

CONSTRAINT_ID = "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c"
FIRST_ENTITY_ID = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
SECOND_ENTITY_ID = "3d3d3d3d-3d3d-4d3d-8d3d-3d3d3d3d3d3d"


def test_coincident_constraint_round_trips_stable_endpoint_references() -> None:
    constraint = SketchConstraint(
        constraint_id=CONSTRAINT_ID,
        kind="coincident",
        references=(
            SketchGeometryReference(FIRST_ENTITY_ID, "start"),
            SketchGeometryReference(SECOND_ENTITY_ID, "end"),
        ),
        source="inferred",
    )

    restored = SketchConstraint.from_mapping(constraint.to_mapping())

    assert restored == constraint
    assert restored.to_mapping()["references"] == [
        {"entity_id": FIRST_ENTITY_ID, "kind": "start"},
        {"entity_id": SECOND_ENTITY_ID, "kind": "end"},
    ]


def test_reference_indices_are_strict_and_stable() -> None:
    reference = SketchGeometryReference(FIRST_ENTITY_ID, "segment", 2)

    assert SketchGeometryReference.from_mapping(reference.to_mapping()) == reference
    with pytest.raises(ValueError, match="nonnegative index"):
        SketchGeometryReference(FIRST_ENTITY_ID, "vertex", -1)
    with pytest.raises(ValueError, match="cannot carry an index"):
        SketchGeometryReference(FIRST_ENTITY_ID, "center", 0)


def test_driving_and_reference_dimensions_keep_mm_units_explicit() -> None:
    dimension = SketchConstraint(
        constraint_id=CONSTRAINT_ID,
        kind="length",
        references=(SketchGeometryReference(FIRST_ENTITY_ID, "geometry"),),
        value=25.0,
        unit="mm",
        driving=False,
    )

    restored = SketchConstraint.from_mapping(dimension.to_mapping())

    assert restored == dimension
    assert restored.driving is False
    assert restored.unit == "mm"


def test_dimension_formatting_round_trips_and_default_format_stays_omitted() -> None:
    reference = SketchConstraint(
        CONSTRAINT_ID,
        "length",
        (SketchGeometryReference(FIRST_ENTITY_ID, "geometry"),),
        value=12.3456,
        unit="mm",
        driving=False,
        precision=3,
        scale=2.5,
    )

    assert SketchConstraint.from_mapping(reference.to_mapping()) == reference
    assert reference.to_mapping()["precision"] == 3
    assert reference.to_mapping()["scale"] == 2.5

    default_format = SketchConstraint(
        CONSTRAINT_ID,
        "length",
        (SketchGeometryReference(FIRST_ENTITY_ID, "geometry"),),
        value=12.0,
        unit="mm",
    ).to_mapping()
    assert "precision" not in default_format
    assert "scale" not in default_format


@pytest.mark.parametrize(
    "mapping_update",
    [
        {"precision": -1},
        {"precision": 9},
        {"precision": True},
        {"scale": 0.0},
        {"scale": 101.0},
        {"scale": float("inf")},
    ],
)
def test_dimension_formatting_rejects_invalid_precision_and_scale(
    mapping_update: dict[str, object],
) -> None:
    mapping = {
        "constraint_id": CONSTRAINT_ID,
        "kind": "length",
        "references": [{"entity_id": FIRST_ENTITY_ID, "kind": "geometry"}],
        "unit": "mm",
        "value": 10.0,
        "driving": True,
        "source": "user",
        **mapping_update,
    }

    with pytest.raises(ValueError, match="dimension precision|dimension scale"):
        SketchConstraint.from_mapping(mapping)


def test_geometric_relation_rejects_dimension_formatting() -> None:
    mapping = {
        "constraint_id": CONSTRAINT_ID,
        "kind": "horizontal",
        "references": [{"entity_id": FIRST_ENTITY_ID, "kind": "geometry"}],
        "driving": True,
        "source": "user",
        "precision": 1,
    }

    with pytest.raises(ValueError, match="cannot carry dimension formatting"):
        SketchConstraint.from_mapping(mapping)


@pytest.mark.parametrize(
    "kind,references,value,unit",
    [
        ("coincident", (), None, None),
        ("length", (SketchGeometryReference(FIRST_ENTITY_ID, "geometry"),), -1.0, "mm"),
        ("angle", (SketchGeometryReference(FIRST_ENTITY_ID, "geometry"),), 90.0, "mm"),
    ],
)
def test_invalid_constraint_cardinality_values_and_units_fail_closed(
    kind: ConstraintKind,
    references: tuple[SketchGeometryReference, ...],
    value: float | None,
    unit: ConstraintUnit | None,
) -> None:
    with pytest.raises(ValueError):
        SketchConstraint(
            CONSTRAINT_ID,
            kind,
            references,
            value,
            unit,
        )


def test_duplicate_geometry_references_are_rejected() -> None:
    reference = SketchGeometryReference(FIRST_ENTITY_ID, "start")
    with pytest.raises(ValueError, match="distinct"):
        SketchConstraint(CONSTRAINT_ID, "coincident", (reference, reference))


def test_constraint_state_digest_changes_without_changing_create_v1_mapping() -> None:
    sketch = Sketch(
        "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a",
        WorkPlaneFrame.xy(),
        (LineEntity(FIRST_ENTITY_ID, (0.0, 0.0), (10.0, 0.0)),),
    )
    constraint = SketchConstraint(
        CONSTRAINT_ID,
        "fixed",
        (SketchGeometryReference(FIRST_ENTITY_ID, "start"),),
    )

    constrained = sketch.with_constraint(constraint, sketch.entities)

    assert constrained.state_digest() != sketch.state_digest()
    assert set(sketch.to_mapping(version=1)) == {"sketch_id", "frame", "entities"}
    assert constrained.to_state_mapping()["constraints"] == [constraint.to_mapping()]
    with pytest.raises(ValueError, match="cannot be represented by mapping version 1"):
        constrained.to_mapping(version=1)
    with pytest.raises(ValueError, match="cannot be represented by mapping version 2"):
        constrained.to_mapping(version=2)
    with pytest.raises(ValueError, match="already exists"):
        constrained.with_constraint(constraint, constrained.entities)
