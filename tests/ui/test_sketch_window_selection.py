# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Window selection follows screen direction and selects curve geometry, not fills."""

from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    SketchEntity,
    SplineEntity,
)
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.ui.sketch_editor import SketchCanvas


@pytest.fixture
def canvas(qtbot: QtBot) -> SketchCanvas:
    widget = SketchCanvas()
    qtbot.addWidget(widget)
    widget.resize(700, 500)
    widget.show()
    qtbot.waitExposed(widget)
    widget.set_tool("选择元素")
    return widget


def select_box(
    canvas: SketchCanvas,
    first: tuple[float, float],
    second: tuple[float, float],
    *,
    two_clicks: bool = False,
    modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
) -> None:
    start, end = canvas.local_to_screen(first), canvas.local_to_screen(second)
    if two_clicks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, modifier, start)
        QTest.mouseMove(canvas, end)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, modifier, end)
    else:
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, modifier, start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, modifier, end)


@pytest.mark.parametrize("two_clicks", [False, True])
@pytest.mark.parametrize("crossing", [False, True])
@pytest.mark.parametrize("upward", [False, True])
def test_window_direction_selects_contained_or_crossing_objects(
    canvas: SketchCanvas, two_clicks: bool, crossing: bool, upward: bool
) -> None:
    inside = LineEntity(uuid4().hex, (-5.0, 0.0), (5.0, 0.0))
    crosses = LineEntity(uuid4().hex, (-30.0, 5.0), (30.0, 5.0))
    outside = LineEntity(uuid4().hex, (25.0, 20.0), (35.0, 20.0))
    canvas.replace_draft_entities((inside, crosses, outside))
    original = tuple(canvas.entities)
    y1, y2 = (-10.0, 10.0) if upward else (10.0, -10.0)
    x1, x2 = (20.0, -20.0) if crossing else (-20.0, 20.0)

    select_box(canvas, (x1, y1), (x2, y2), two_clicks=two_clicks)

    expected = {inside.entity_id, crosses.entity_id} if crossing else {inside.entity_id}
    assert canvas.selected_entity_ids == expected
    assert tuple(canvas.entities) == original
    assert not canvas.has_active_edit_gesture


@pytest.mark.parametrize(
    ("entity", "first", "second", "expected"),
    [
        # Crossing means touching the actual outline, not overlapping its bounding box/fill.
        (CircleEntity(uuid4().hex, (0.0, 0.0), 20.0), (5.0, 5.0), (-5.0, -5.0), False),
        (CircleEntity(uuid4().hex, (0.0, 0.0), 20.0), (19.0, 19.0), (17.0, 17.0), False),
        (CircleEntity(uuid4().hex, (0.0, 0.0), 20.0), (20.0, 5.0), (18.0, -5.0), True),
        (CircleEntity(uuid4().hex, (0.0, 0.0), 20.0), (22.0, 5.0), (20.0, -5.0), True),
        (CircleEntity(uuid4().hex, (0.0, 0.0), 5.0), (-10.0, 10.0), (10.0, -10.0), True),
        (CircleEntity(uuid4().hex, (0.0, 0.0), 20.0), (-10.0, 10.0), (10.0, -10.0), False),
        # Arc extrema matter even when both endpoints are inside the box.
        (ArcEntity(uuid4().hex, (0.0, 0.0), 20.0, 0.0, 180.0), (-25.0, 5.0), (25.0, -5.0), False),
        (ArcEntity(uuid4().hex, (0.0, 0.0), 20.0, 0.0, 180.0), (-25.0, 25.0), (25.0, -5.0), True),
        (ArcEntity(uuid4().hex, (0.0, 0.0), 20.0, 0.0, 180.0), (5.0, -18.0), (-5.0, -22.0), False),
        (ArcEntity(uuid4().hex, (0.0, 0.0), 20.0, 0.0, -180.0), (5.0, -18.0), (-5.0, -22.0), True),
        (
            RectangleEntity(uuid4().hex, (-20.0, -20.0), (20.0, 20.0)),
            (5.0, 5.0),
            (-5.0, -5.0),
            False,
        ),
        (
            RectangleEntity(uuid4().hex, (-20.0, -20.0), (20.0, 20.0)),
            (22.0, 5.0),
            (18.0, -5.0),
            True,
        ),
        (
            PolylineEntity(uuid4().hex, ((-20.0, 0.0), (0.0, 20.0), (20.0, 0.0)), closed=True),
            (5.0, 2.0),
            (-5.0, -2.0),
            True,
        ),
        (
            PolylineEntity(uuid4().hex, ((-20.0, 0.0), (0.0, 20.0), (20.0, 0.0))),
            (5.0, 2.0),
            (-5.0, -2.0),
            False,
        ),
        (
            SplineEntity(uuid4().hex, ((-20.0, 0.0), (-10.0, 20.0), (10.0, 20.0), (20.0, 0.0))),
            (5.0, 17.0),
            (-5.0, 13.0),
            True,
        ),
        (LineEntity(uuid4().hex, (-20.0, 15.0), (15.0, 20.0)), (5.0, 5.0), (-5.0, -5.0), False),
    ],
)
def test_window_tests_curve_geometry(
    canvas: SketchCanvas,
    entity: SketchEntity,
    first: tuple[float, float],
    second: tuple[float, float],
    expected: bool,
) -> None:
    from mycad.ui.sketch_selection import entity_in_selection_box

    assert entity_in_selection_box(entity, first, second, crossing=first[0] > second[0]) is expected


def test_window_filters_hidden_layers_and_preserves_locked_selection(canvas: SketchCanvas) -> None:
    canvas.set_layer_table(
        SketchLayerTable()
        .add(SketchLayer("hidden", visible=False))
        .add(SketchLayer("locked", locked=True)),
        "0",
    )
    hidden = LineEntity(uuid4().hex, (-5.0, 0.0), (5.0, 0.0), layer_name="hidden")
    locked = LineEntity(uuid4().hex, (-5.0, 5.0), (5.0, 5.0), layer_name="locked")
    canvas.replace_draft_entities((hidden, locked))
    select_box(canvas, (-20.0, 15.0), (20.0, -15.0))
    assert canvas.selected_entity_ids == {locked.entity_id}
    canvas.begin_transform("move")
    assert not canvas.has_active_edit_gesture
    assert tuple(canvas.entities) == (hidden, locked)


def test_window_modifiers_add_and_remove(canvas: SketchCanvas) -> None:
    left = LineEntity(uuid4().hex, (-30.0, 0.0), (-20.0, 0.0))
    right = LineEntity(uuid4().hex, (20.0, 0.0), (30.0, 0.0))
    canvas.replace_draft_entities((left, right))
    canvas.selected_entity_ids = {left.entity_id}
    select_box(canvas, (15.0, 10.0), (35.0, -10.0), modifier=Qt.KeyboardModifier.ControlModifier)
    assert canvas.selected_entity_ids == {left.entity_id, right.entity_id}
    select_box(canvas, (-35.0, 10.0), (-15.0, -10.0), modifier=Qt.KeyboardModifier.ShiftModifier)
    assert canvas.selected_entity_ids == {right.entity_id}


def test_escape_cancels_window_and_release_does_not_select(canvas: SketchCanvas) -> None:
    line = LineEntity(uuid4().hex, (-5.0, 0.0), (5.0, 0.0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    start, end = canvas.local_to_screen((-20.0, 15.0)), canvas.local_to_screen((20.0, -15.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.selected_entity_ids == {line.entity_id}
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    assert canvas.selected_entity_ids == {line.entity_id}


def test_command_first_window_selection_moves_all_selected_and_undoes(canvas: SketchCanvas) -> None:
    lines = (
        LineEntity(uuid4().hex, (-5.0, 0.0), (5.0, 0.0)),
        LineEntity(uuid4().hex, (-5.0, 5.0), (5.0, 5.0)),
    )
    canvas.replace_draft_entities(lines)
    canvas.begin_transform("move")
    select_box(canvas, (-20.0, 15.0), (20.0, -15.0))
    assert canvas.selected_entity_ids == {line.entity_id for line in lines}
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((20.0, 0.0), exact_point=True)
    assert tuple(canvas.entities) == (
        LineEntity(lines[0].entity_id, (15.0, 0.0), (25.0, 0.0)),
        LineEntity(lines[1].entity_id, (15.0, 5.0), (25.0, 5.0)),
    )
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == lines


@pytest.mark.parametrize("command_first", [False, True])
def test_shift_point_removes_without_dragging_control_point(
    canvas: SketchCanvas, command_first: bool
) -> None:
    left = LineEntity(uuid4().hex, (-30.0, 0.0), (-20.0, 0.0))
    right = LineEntity(uuid4().hex, (20.0, 0.0), (30.0, 0.0))
    canvas.replace_draft_entities((left, right))
    if command_first:
        canvas.begin_transform("copy")
    canvas.selected_entity_ids = {left.entity_id, right.entity_id}
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        canvas.local_to_screen(left.start_mm),
    )
    assert canvas.selected_entity_ids == {right.entity_id}
    assert tuple(canvas.entities) == (left, right)


def test_enter_finishes_pending_window_before_transform_base(canvas: SketchCanvas) -> None:
    first = LineEntity(uuid4().hex, (-5.0, 0.0), (5.0, 0.0))
    second = LineEntity(uuid4().hex, (-5.0, 5.0), (5.0, 5.0))
    canvas.replace_draft_entities((first, second))
    canvas.begin_transform("copy")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-20.0, 15.0)))
    QTest.mouseMove(canvas, canvas.local_to_screen((20.0, -15.0)))
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.selected_entity_ids == {first.entity_id, second.entity_id}
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20.0, 0.0)))
    assert len(canvas.entities) == 4
    assert not canvas.has_active_edit_gesture


def test_switching_tools_discards_pending_window(canvas: SketchCanvas) -> None:
    line = LineEntity(uuid4().hex, (-5.0, 0.0), (5.0, 0.0))
    canvas.replace_draft_entities((line,))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-20.0, 15.0)))
    QTest.mouseMove(canvas, canvas.local_to_screen((20.0, -15.0)))
    canvas.set_tool("直线")
    assert not canvas.has_active_edit_gesture
    canvas.add_coordinate_point((30.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((40.0, 0.0), exact_point=True)
    assert len(canvas.entities) == 2
    assert canvas.entities[0] == line
