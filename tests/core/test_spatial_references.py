# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Spatial references must identify prior outputs without runtime topology IDs."""

import pytest

from mycad.core.exceptions import ValidationError
from mycad.core.spatial_references import SpatialReference, resolve_prior_output

SOURCE = "1234567890abcdef1234567890abcdef"


def test_coordinate_reference_roundtrip_and_prior_output_resolution() -> None:
    reference = SpatialReference.from_mapping(
        {"kind": "coordinate_system", "source_instance_id": SOURCE, "role": "coordinate_system"}
    )
    assert reference.to_mapping() == {
        "kind": "coordinate_system",
        "source_instance_id": SOURCE,
        "role": "coordinate_system",
    }
    assert resolve_prior_output(reference, {SOURCE: ("coordinate_system", "frame")}) == "frame"


def test_missing_forward_and_wrong_kind_fail_without_fallback() -> None:
    reference = SpatialReference.from_mapping(
        {"kind": "datum_plane", "source_instance_id": SOURCE, "role": "plane"}
    )
    with pytest.raises(ValidationError):
        resolve_prior_output(reference, {})
    with pytest.raises(ValidationError):
        resolve_prior_output(reference, {SOURCE: ("coordinate_system", "frame")})


@pytest.mark.parametrize(
    "record",
    [
        {"kind": "world", "source_instance_id": SOURCE},
        {"kind": "coordinate_system", "source_instance_id": "A" * 32, "role": "coordinate_system"},
        {"kind": "datum_plane", "source_instance_id": SOURCE, "role": "coordinate_system"},
        {"kind": "datum_plane", "source_instance_id": SOURCE, "role": "plane", "index": 3},
    ],
)
def test_rejects_ambiguous_or_noncanonical_reference(record: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SpatialReference.from_mapping(record)
