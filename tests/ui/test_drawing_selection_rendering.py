# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Selecting one object must not fill nearby unselected shapes."""

from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import CircleEntity, LineEntity, RectangleEntity, Sketch, WorkPlaneFrame
from mycad.ui.sketch_editor import SketchEditorDialog


@pytest.mark.parametrize("saved", [False, True])
def test_selected_line_grips_do_not_fill_other_shapes(qtbot: QtBot, saved: bool) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    line = LineEntity(uuid4().hex, (-20, 0), (-10, 0))
    circle = CircleEntity(uuid4().hex, (5, 8), 4)
    rectangle = RectangleEntity(uuid4().hex, (15, 4), (23, 12))
    if saved:
        canvas.set_background_sketches(
            (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle, rectangle)),),
            WorkPlaneFrame.xy(),
        )
    else:
        canvas.entities = [line, circle, rectangle]
    points = [canvas.local_to_screen((5, 8)), canvas.local_to_screen((19, 8))]
    before = canvas.grab().toImage()
    ratio = before.devicePixelRatio()
    pixels_before = [before.pixelColor(round(p.x() * ratio), round(p.y() * ratio)) for p in points]
    canvas.selected_entity_ids = {line.entity_id}
    after = canvas.grab().toImage()
    assert [
        after.pixelColor(round(p.x() * ratio), round(p.y() * ratio)) for p in points
    ] == pixels_before
    assert canvas.selected_entity_ids == {line.entity_id}
