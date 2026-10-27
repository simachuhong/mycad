# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimension placement is durable model-space data, with legacy defaults."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_dimension_presentation_roundtrip_and_legacy_defaults() -> None:
    legacy = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(uuid4().hex, "geometry"),), 10, "mm"
    )
    assert legacy.position_mm is None
    assert "position_mm" not in legacy.to_mapping()
    placed = replace(
        legacy, position_mm=(4.0, -12.0), text_position_mm=(8.0, -13.0), axis="horizontal"
    )
    assert SketchConstraint.from_mapping(placed.to_mapping()) == placed


@pytest.mark.parametrize("point", [(float("nan"), 0), (True, 0), (1,), (0, float("inf"))])
def test_invalid_dimension_placement_is_rejected(point: object) -> None:
    record = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(uuid4().hex, "geometry"),), 5, "mm"
    ).to_mapping()
    record["position_mm"] = point
    with pytest.raises(ValueError):
        SketchConstraint.from_mapping(record)
