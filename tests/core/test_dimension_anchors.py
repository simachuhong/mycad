# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Edit anchoring is durable dimension metadata, not an extra relation."""

from uuid import uuid4

import pytest

from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def dimension() -> SketchConstraint:
    return SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(uuid4().hex, "geometry"),), 30, "mm"
    )


@pytest.mark.parametrize("mode", ["auto", "start", "end", "symmetric"])
def test_anchor_policy_roundtrip_preserves_legacy_default(mode: str) -> None:
    legacy = dimension().to_mapping()
    parsed = SketchConstraint.from_mapping({**legacy, "anchor_mode": mode})
    assert parsed.anchor_mode == mode
    assert SketchConstraint.from_mapping(parsed.to_mapping()) == parsed
    assert ("anchor_mode" in parsed.to_mapping()) == (mode != "auto")
    assert SketchConstraint.from_mapping(legacy).anchor_mode == "auto"


def test_non_linear_anchor_and_unknown_policy_are_rejected() -> None:
    raw = dimension().to_mapping()
    with pytest.raises(ValueError, match="anchor"):
        SketchConstraint.from_mapping({**raw, "anchor_mode": "invalid"})
    with pytest.raises(ValueError, match="linear"):
        SketchConstraint.from_mapping({**raw, "kind": "radius", "anchor_mode": "end"})
