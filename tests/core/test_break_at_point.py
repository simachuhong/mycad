# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Focused geometry coverage for U09's single-point break."""

import math
from uuid import uuid4

import pytest

from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, PolylineEntity
from mycad.core.sketch_edit import break_entity_at_point


def test_break_at_point_open_geometry() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="A")
    first, second = break_entity_at_point(line, (3, 4))
    assert isinstance(first, LineEntity) and isinstance(second, LineEntity)
    assert first.end_mm == second.start_mm == (3, 0)
    assert first.entity_id == line.entity_id and second.entity_id != line.entity_id
    assert first.layer_name == second.layer_name == "A"

    arc = ArcEntity(uuid4().hex, (0, 0), 5, 90, -180)
    first, second = break_entity_at_point(arc, (8, 0))
    assert isinstance(first, ArcEntity) and isinstance(second, ArcEntity)
    assert first.sweep_angle_deg == pytest.approx(-90)
    assert second.start_angle_deg == pytest.approx(0)
    assert second.sweep_angle_deg == pytest.approx(-90)

    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(1.0, 0.0))
    first, second = break_entity_at_point(polyline, (5, -8))
    assert isinstance(first, PolylineEntity) and isinstance(second, PolylineEntity)
    assert first.points_mm[-1] == pytest.approx((5, -5))
    assert first.bulges[0] == pytest.approx(math.tan(math.pi / 8))
    assert second.bulges[0] == pytest.approx(math.tan(math.pi / 8))
    assert second.points_mm[-1] == (10, 10)
    first, second = break_entity_at_point(polyline, (10, 0))
    assert isinstance(first, PolylineEntity) and isinstance(second, PolylineEntity)
    assert first.points_mm[-1] == second.points_mm[0] == (10, 0)

    with pytest.raises(ValueError):
        break_entity_at_point(CircleEntity(uuid4().hex, (0, 0), 2), (2, 0))
    with pytest.raises(ValueError):
        break_entity_at_point(line, (-2, 0))


def test_break_projection_rejects_ambiguous_nearest_path_only() -> None:
    path = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (5, 5)), bulges=(1, 0))
    first, second = break_entity_at_point(path, (5, 0))
    assert isinstance(first, PolylineEntity) and isinstance(second, PolylineEntity)
    assert first.points_mm[-1] == pytest.approx((7.5, 2.5))
    crossing = PolylineEntity(uuid4().hex, ((0, 0), (10, 10), (0, 10), (10, 0)))
    with pytest.raises(ValueError, match="距离相同"):
        break_entity_at_point(crossing, (5, 5))
    arc = ArcEntity(uuid4().hex, (0, 0), 5, -45, 90)
    with pytest.raises(ValueError, match="距离相同"):
        break_entity_at_point(arc, (-10, 0))
