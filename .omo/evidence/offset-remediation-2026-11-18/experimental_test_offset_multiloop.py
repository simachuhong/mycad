# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Geometric offset preserves all components when a narrow neck disappears."""

from uuid import uuid4

import pytest

from mycad.core.sketch import PolylineEntity
from mycad.geom.drawing_offset import offset_closed_polyline


@pytest.mark.parametrize("reverse", [False, True])
def test_inward_offset_returns_both_components(reverse: bool) -> None:
    points = (
        (0, 0),
        (4, 0),
        (4, 1),
        (6, 1),
        (6, 0),
        (10, 0),
        (10, 4),
        (6, 4),
        (6, 3),
        (4, 3),
        (4, 4),
        (0, 4),
    )
    source = PolylineEntity(uuid4().hex, tuple(reversed(points)) if reverse else points, True)
    result = offset_closed_polyline(source, -1.1 if reverse else 1.1)
    assert len(result) == 2
    assert all(item.closed and item.layer_name == source.layer_name for item in result)
    assert len({item.entity_id for item in result}) == 2
    boxes = sorted(
        (
            min(x for x, y in item.points_mm),
            max(x for x, y in item.points_mm),
            min(y for x, y in item.points_mm),
            max(y for x, y in item.points_mm),
        )
        for item in result
    )
    assert boxes[0] == pytest.approx((1.1, 2.9, 1.1, 2.9))
    assert boxes[1] == pytest.approx((7.1, 8.9, 1.1, 2.9))
