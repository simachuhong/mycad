# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Angular and arc-length dimensions follow the drawing's line style."""

import math
from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.sketch import ArcEntity, LineEntity
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.sketch_editor import SketchCanvas


@pytest.mark.parametrize("kind", ("angle", "arc_length"))
@pytest.mark.parametrize("direction", (1, -1))
def test_curved_dimension_line_style(qtbot: QtBot, kind: str, direction: int) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(900, 700)
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 20 * direction))
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 90 * direction)
    entities = {entity.entity_id: entity for entity in (first, second, arc)}
    refs = (
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        )
        if kind == "angle"
        else (SketchGeometryReference(arc.entity_id, "geometry"),)
    )
    dim = SketchConstraint(
        uuid4().hex,
        kind,
        refs,
        90 if kind == "angle" else 5 * math.pi,
        "deg" if kind == "angle" else "mm",
        driving=False,
        position_mm=(15, 15 * direction),
        style_name="测试",
    )
    base = DimensionStyle("测试")
    canvas.drawing_dimension_styles = DimensionStyleTable((base,), "测试")
    original = canvas.dimension_layout(dim, entities)
    assert original is not None
    style = DimensionStyle("测试", dimline_extension=2, extline_extension=3, extline_offset=1)
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), "测试")
    changed = canvas.dimension_layout(dim, entities)
    assert changed is not None
    assert changed.arrows == original.arrows
    assert len(changed.lines) > len(original.lines)
    for before, after in zip(original.lines[-2:], changed.lines[-2:], strict=True):
        assert math.hypot(
            after[0].x() - before[0].x(), after[0].y() - before[0].y()
        ) == pytest.approx(canvas.view_scale)
        assert math.hypot(
            after[1].x() - before[1].x(), after[1].y() - before[1].y()
        ) == pytest.approx(3 * canvas.view_scale)
