# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Radial dimensions use the drawing style's center mark settings."""

from dataclasses import replace
from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.sketch import ArcEntity, CircleEntity
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.drawing_dimension_styles import DrawingDimensionStylesDialog
from mycad.ui.sketch_editor import SketchCanvas


@pytest.mark.parametrize("kind", ("radius", "diameter"))
@pytest.mark.parametrize("entity_kind", ("circle", "arc"))
@pytest.mark.parametrize(("mark", "extra"), (("none", 0), ("mark", 2), ("line", 6)))
def test_radial_center_marks_follow_style_and_location(
    qtbot: QtBot, kind: str, entity_kind: str, mark: str, extra: int
) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    entity = (
        CircleEntity(uuid4().hex, (0, 0), 10)
        if entity_kind == "circle"
        else ArcEntity(uuid4().hex, (0, 0), 10, 0, 180)
    )
    canvas.entities = [entity]
    style = DimensionStyle("测试", center_mark=mark, center_size=2)
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    dimension = SketchConstraint(
        uuid4().hex,
        kind,
        (SketchGeometryReference(entity.entity_id, "geometry"),),
        10 if kind == "radius" else 20,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    assert len(layout.lines) == 1 + extra
    inside = canvas.dimension_layout(
        replace(dimension, position_mm=(5, 0)), canvas.dimension_entities()
    )
    assert inside is not None and len(inside.lines) == 1

    legacy = canvas.dimension_layout(
        replace(dimension, position_mm=None), canvas.dimension_entities()
    )
    assert legacy is not None and len(legacy.lines) == 1 + extra


def test_center_mark_settings_stage_and_cancel(qtbot: QtBot) -> None:
    style = DimensionStyle("标准")
    table = DimensionStyleTable((style,), style.name)
    dialog = DrawingDimensionStylesDialog(table, frozenset())
    qtbot.addWidget(dialog)
    dialog.center_mark.setCurrentIndex(dialog.center_mark.findData("line"))
    dialog.center_size.setValue(4)
    dialog.save_button.click()
    assert dialog.table.current.center_mark == "line"
    assert dialog.table.current.center_size == 4
    dialog.reject()
    assert table.current == style
