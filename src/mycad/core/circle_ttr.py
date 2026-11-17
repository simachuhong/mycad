# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Construct a circle tangent to two selected finite sketch curves."""

from __future__ import annotations

from mycad.core.circle_fillet import circle_fillet_notrim
from mycad.core.line_circle_fillet import line_circle_fillet_notrim
from mycad.core.line_fillet import line_fillet
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Point2D

type TangentSource = LineEntity | CircleEntity | ArcEntity


def circle_ttr(
    first: TangentSource,
    second: TangentSource,
    first_pick: Point2D,
    second_pick: Point2D,
    radius: float,
    identity: str,
    *,
    construction: bool = False,
    layer_name: str = "0",
) -> CircleEntity:
    """Select a finite-curve tangent center using the two pick locations."""
    if isinstance(first, LineEntity) and isinstance(second, LineEntity):
        _, _, arc = line_fillet(first, second, first_pick, second_pick, radius, identity)
    elif isinstance(first, LineEntity) and isinstance(second, CircleEntity | ArcEntity):
        arc = line_circle_fillet_notrim(first, second, first_pick, second_pick, radius, identity)
    elif isinstance(second, LineEntity) and isinstance(first, CircleEntity | ArcEntity):
        arc = line_circle_fillet_notrim(second, first, second_pick, first_pick, radius, identity)
    elif isinstance(first, CircleEntity | ArcEntity) and isinstance(
        second, CircleEntity | ArcEntity
    ):
        arc = circle_fillet_notrim(first, second, first_pick, second_pick, radius, identity)
    else:
        raise ValueError("请选择直线、圆或圆弧。")
    return CircleEntity(identity, arc.center_mm, radius, construction, layer_name)
