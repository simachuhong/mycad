# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Interactive quick measurement is transient and read-only."""

from uuid import uuid4

from PySide6.QtCore import QEvent, Qt, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mycad.core.drawing_quick_measure import LinePairMeasurement
from mycad.core.drawing_quick_regions import LinearRegion
from mycad.core.sketch import LineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def test_quick_line_pair_preview_tracks_mouse_and_clears(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    lines = (
        LineEntity(uuid4().hex, (-20, -5), (20, -5)),
        LineEntity(uuid4().hex, (-20, 5), (20, 5)),
    )
    assert canvas.replace_draft_entities(lines)
    previous_history = canvas.history_position
    bar = editor.drawing_command_bar.input
    for value in ("MEASUREGEOM", "Q"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseMove(canvas, canvas.local_to_screen((0, 0)))
    preview = canvas.quick_measure_preview
    assert isinstance(preview, LinePairMeasurement)
    assert preview.distance_mm == 10
    assert preview.angle_deg == 0
    assert "10" in editor.drawing_command_bar.status.text()
    assert tuple(canvas.entities) == lines and canvas.history_position == previous_history
    QApplication.sendEvent(canvas, QEvent(QEvent.Type.Leave))
    assert canvas.quick_measure_preview is None
    QTest.mouseMove(canvas, canvas.local_to_screen((1, 0)))
    assert canvas.quick_measure_preview is not None
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.quick_measure_preview is None
    assert tuple(canvas.entities) == lines and canvas.history_position == previous_history


def test_quick_preview_clears_after_geometry_changes(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    lines = (
        LineEntity(uuid4().hex, (-20, -5), (20, -5)),
        LineEntity(uuid4().hex, (-20, 5), (20, 5)),
    )
    assert canvas.replace_draft_entities(lines)
    bar = editor.drawing_command_bar.input
    for value in ("MEASUREGEOM", "Q"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseMove(canvas, canvas.local_to_screen((0, 0)))
    assert canvas.quick_measure_preview is not None
    assert canvas.replace_draft_entities((lines[0],))
    assert canvas.quick_measure_preview is None


def test_quick_circle_radius_tracks_cursor_and_does_not_edit(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    assert canvas.replace_draft_entities((circle,))
    previous_history = canvas.history_position
    bar = editor.drawing_command_bar.input
    for value in ("MEASUREGEOM", "Q"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseMove(canvas, canvas.local_to_screen((10, 0)))
    assert "半径 10" in editor.drawing_command_bar.status.text()
    assert "直径 20" in editor.drawing_command_bar.status.text()
    assert canvas.entities == [circle] and canvas.history_position == previous_history
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.quick_measure_preview is None


def test_quick_arc_and_polyline_arc_use_their_actual_radius(qtbot: QtBot) -> None:
    from mycad.core.sketch import ArcEntity, PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    arc = ArcEntity(uuid4().hex, (-30, 0), 10, 0, 90)
    polyline = PolylineEntity(uuid4().hex, ((10, 0), (30, 0)), False, bulges=(1.0,))
    assert canvas.replace_draft_entities((arc, polyline))
    bar = editor.drawing_command_bar.input
    for value in ("MEASUREGEOM", "Q"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseMove(canvas, canvas.local_to_screen((-20, 0)))
    assert "半径 10" in editor.drawing_command_bar.status.text()
    QTest.mouseMove(canvas, canvas.local_to_screen((20, -10)))
    assert "半径 10" in editor.drawing_command_bar.status.text()
    QTest.mouseMove(canvas, canvas.local_to_screen((0, 40)))
    assert canvas.quick_measure_preview is None


def test_quick_ambiguous_circles_do_not_fall_back_to_unrelated_lines(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.entities = [
        CircleEntity(uuid4().hex, (0, 0), 10),
        CircleEntity(uuid4().hex, (0, 0), 10),
        LineEntity(uuid4().hex, (0, -5), (20, -5)),
        LineEntity(uuid4().hex, (0, 5), (20, 5)),
    ]
    canvas.update_quick_measure((10, 0))
    assert canvas.quick_measure_preview is None


def test_quick_line_segments_from_rectangle_and_polyline(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    rectangle = RectangleEntity(uuid4().hex, (-20, -5), (20, 5))
    canvas.entities = [rectangle]
    canvas.update_quick_measure((0, 0))
    preview = canvas.quick_measure_preview
    assert isinstance(preview, LinePairMeasurement)
    assert preview.distance_mm == 10
    assert preview.angle_deg == 0
    polyline = PolylineEntity(uuid4().hex, ((-20, -5), (20, -5), (20, 5), (-20, 5)), True)
    canvas.entities = [polyline]
    canvas.update_quick_measure((0, 0))
    preview = canvas.quick_measure_preview
    assert isinstance(preview, LinePairMeasurement)
    assert preview.distance_mm == 10
    assert preview.angle_deg == 0


def test_quick_curve_pair_distances_show_between_curves(qtbot: QtBot) -> None:
    from mycad.core.drawing_quick_measure import CurvePairMeasurement
    from mycad.core.sketch import CircleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    line = LineEntity(uuid4().hex, (-10, 15), (10, 15))
    assert canvas.replace_draft_entities((circle, line))
    history = canvas.history_position
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseMove(canvas, canvas.local_to_screen((0, 10)))
    assert isinstance(canvas.quick_measure_preview, CurvePairMeasurement)
    assert canvas.quick_measure_preview.distance_mm == 10
    assert "距离 10" in bar.status.text()
    assert tuple(canvas.entities) == (circle, line) and canvas.history_position == history
    other = CircleEntity(uuid4().hex, (24, 0), 5)
    assert canvas.replace_draft_entities((circle, other))
    QTest.mouseMove(canvas, canvas.local_to_screen((12, 0)))
    assert isinstance(canvas.quick_measure_preview, CurvePairMeasurement)
    assert canvas.quick_measure_preview.distance_mm == 14
    assert "距离 14" in bar.status.text()


def test_quick_region_click_and_shift_accumulate_are_read_only(qtbot: QtBot) -> None:
    from mycad.core.sketch import RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    first = RectangleEntity(uuid4().hex, (-20, -5), (-10, 5))
    second = RectangleEntity(uuid4().hex, (10, -5), (14, 5))
    assert canvas.replace_draft_entities((first, second))
    history = canvas.history_position
    bar = editor.drawing_command_bar.input
    for value in ("MEASUREGEOM", "Q"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-15, 0)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 100" in editor.drawing_command_bar.status.text()
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((12, 0)),
    )
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 2, timeout=10000)
    assert "面积 140" in editor.drawing_command_bar.status.text()
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((-15, 0)),
    )
    assert len(canvas.quick_measure_regions) == 1
    assert "面积 40" in editor.drawing_command_bar.status.text()
    assert canvas.entities == [first, second] and canvas.history_position == history
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.quick_measure_regions == ()


def test_quick_region_worker_discards_result_after_geometry_change(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from threading import Event

    from mycad.core.sketch import CircleEntity, RectangleEntity
    from mycad.ui import drawing2d_command_bar as command_module

    started, release = Event(), Event()
    original = command_module.build_quick_regions

    def delayed(
        lines: tuple[LineEntity, ...], circles: tuple[CircleEntity, ...]
    ) -> tuple[LinearRegion, ...]:
        started.set()
        if not release.wait(5):
            raise ValueError("timeout")
        return original(lines, circles)

    monkeypatch.setattr(command_module, "build_quick_regions", delayed)
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (-10, -10), (10, 10))
    assert canvas.replace_draft_entities((rectangle,))
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    qtbot.waitUntil(started.is_set, timeout=10000)
    assert canvas.replace_draft_entities(())
    release.set()
    qtbot.waitUntil(lambda: QThreadPool.globalInstance().activeThreadCount() == 0, timeout=10000)
    QApplication.processEvents()
    assert canvas.quick_measure_regions == ()
    assert "面积 400" not in bar.status.text()


def test_quick_circle_region_and_rectangular_hole_are_clickable(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (-10, -10), (10, 10))
    circle = CircleEntity(uuid4().hex, (0, 0), 4)
    assert canvas.replace_draft_entities((rectangle, circle))
    bar = editor.drawing_command_bar.input
    for value in ("MEASUREGEOM", "Q"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 50.2655" in editor.drawing_command_bar.status.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((7, 0)))
    assert len(canvas.quick_measure_regions) == 1
    assert "面积 349.735" in editor.drawing_command_bar.status.text()
    assert canvas.entities == [rectangle, circle]


def test_quick_curved_polyline_region_is_clickable(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    curved = PolylineEntity(
        uuid4().hex,
        ((-10, 0), (10, 0), (10, 10), (-10, 10)),
        True,
        bulges=(1.0, 0.0, 0.0, 0.0),
    )
    assert canvas.replace_draft_entities((curved,))
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, -5)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 357.08" in bar.status.text()
    assert canvas.entities == [curved]


def test_quick_arc_distances_include_polyline_arc_segments(qtbot: QtBot) -> None:
    from mycad.core.drawing_quick_measure import CurvePairMeasurement
    from mycad.core.sketch import ArcEntity, CircleEntity, PolylineEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 180)
    line = LineEntity(uuid4().hex, (-10, 15), (10, 15))
    canvas.entities = [arc, line]
    canvas.update_quick_measure((0, 10))
    assert isinstance(canvas.quick_measure_preview, CurvePairMeasurement)
    assert canvas.quick_measure_preview.distance_mm == 10

    polyline = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), False, bulges=(-1.0,))
    canvas.entities = [polyline, line]
    canvas.update_quick_measure((0, 10))
    assert isinstance(canvas.quick_measure_preview, CurvePairMeasurement)
    assert canvas.quick_measure_preview.distance_mm == 10

    arc = ArcEntity(uuid4().hex, (0, 0), 5, -90, 180)
    circle = CircleEntity(uuid4().hex, (24, 0), 5)
    canvas.entities = [arc, circle]
    canvas.update_quick_measure((12, 0))
    assert isinstance(canvas.quick_measure_preview, CurvePairMeasurement)
    assert canvas.quick_measure_preview.distance_mm == 14


def test_quick_right_angle_marker_is_drawn_at_intersection(qtbot: QtBot) -> None:
    from PySide6.QtCore import QPoint

    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(600, 500)
    canvas.entities = [
        LineEntity(uuid4().hex, (-20, 0), (20, 0)),
        LineEntity(uuid4().hex, (0, -20), (0, 20)),
    ]
    canvas.show()
    canvas.update_quick_measure((-4, 4))
    preview = canvas.quick_measure_preview
    assert isinstance(preview, LinePairMeasurement)
    assert preview.right_angle_directions is not None
    image = canvas.grab().toImage()
    corner = canvas.local_to_screen((0, 0)) + QPoint(-10, -10)
    color = image.pixelColor(corner)
    assert color.red() > 180 and 65 < color.green() < 170 and color.blue() < 90


def test_quick_click_circle_regions_split_by_line(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    line = LineEntity(uuid4().hex, (-20, 0), (20, 0))
    assert canvas.replace_draft_entities((circle, line))
    history = canvas.history_position
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 5)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 157.08" in bar.status.text()
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((0, -5)),
    )
    assert len(canvas.quick_measure_regions) == 2
    assert "面积 314.159" in bar.status.text()
    assert tuple(canvas.entities) == (circle, line) and canvas.history_position == history


def test_quick_click_region_bounded_by_arc_and_lines(qtbot: QtBot) -> None:
    from mycad.core.sketch import ArcEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 180)
    diameter = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    bisector = LineEntity(uuid4().hex, (0, 0), (0, 10))
    assert canvas.replace_draft_entities((arc, diameter, bisector))
    history = canvas.history_position
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 3)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 78.5398" in bar.status.text()
    assert (
        tuple(canvas.entities) == (arc, diameter, bisector) and canvas.history_position == history
    )


def test_quick_click_region_bounded_by_open_curved_polyline(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    curved = PolylineEntity(uuid4().hex, ((-10, 0), (10, 0)), False, bulges=(-1.0,))
    diameter = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    assert canvas.replace_draft_entities((curved, diameter))
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 5)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 157.08" in bar.status.text()
    assert tuple(canvas.entities) == (curved, diameter)


def test_quick_click_closed_curved_polyline_split_by_line(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    curved = PolylineEntity(
        uuid4().hex,
        ((-10, 0), (10, 0), (10, 10), (-10, 10)),
        True,
        bulges=(1.0, 0.0, 0.0, 0.0),
    )
    splitter = LineEntity(uuid4().hex, (0, -15), (0, 15))
    assert canvas.replace_draft_entities((curved, splitter))
    history = canvas.history_position
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-5, 2)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 178.54" in bar.status.text()
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((5, 2)),
    )
    assert len(canvas.quick_measure_regions) == 2
    assert "面积 357.08" in bar.status.text()
    assert tuple(canvas.entities) == (curved, splitter) and canvas.history_position == history


def test_quick_click_circle_tangent_inside_rectangle(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    rectangle = RectangleEntity(uuid4().hex, (-10, -10), (10, 10))
    assert canvas.replace_draft_entities((circle, rectangle))
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 314.159" in bar.status.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((9, 9)))
    assert len(canvas.quick_measure_regions) == 1
    assert "面积 21.4602" in bar.status.text()
    assert tuple(canvas.entities) == (circle, rectangle)


def test_quick_click_internal_tangent_circle_hole(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    outer = CircleEntity(uuid4().hex, (0, 0), 10)
    inner = CircleEntity(uuid4().hex, (6, 0), 4)
    assert canvas.replace_draft_entities((outer, inner))
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-4, 0)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 263.894" in bar.status.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((6, 0)))
    assert "面积 50.2655" in bar.status.text()
    assert tuple(canvas.entities) == (outer, inner)


def test_quick_click_semicircle_tangent_to_rectangle(qtbot: QtBot) -> None:
    from mycad.core.sketch import ArcEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 180)
    rectangle = RectangleEntity(uuid4().hex, (-10, 0), (10, 10))
    assert canvas.replace_draft_entities((arc, rectangle))
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 5)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 157.08" in bar.status.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((9, 9)))
    assert "面积 21.4602" in bar.status.text()
    assert tuple(canvas.entities) == (arc, rectangle)


def test_quick_measure_duplicate_circle_and_overlapping_lines(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    entities = (
        CircleEntity(uuid4().hex, (0, 0), 10),
        CircleEntity(uuid4().hex, (0, 0), 10),
        LineEntity(uuid4().hex, (-20, 0), (20, 0)),
        LineEntity(uuid4().hex, (5, 0), (-5, 0)),
    )
    assert canvas.replace_draft_entities(entities)
    history = canvas.history_position
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 5)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 157.08" in bar.status.text()
    assert tuple(canvas.entities) == entities and canvas.history_position == history


def test_quick_measure_overlapping_arcs(qtbot: QtBot) -> None:
    from mycad.core.sketch import ArcEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    entities = (
        ArcEntity(uuid4().hex, (0, 0), 10, 0, 180),
        ArcEntity(uuid4().hex, (0, 0), 10, 150, -120),
        LineEntity(uuid4().hex, (-10, 0), (10, 0)),
    )
    assert canvas.replace_draft_entities(entities)
    history = canvas.history_position
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 5)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 157.08" in bar.status.text()
    assert tuple(canvas.entities) == entities and canvas.history_position == history


def test_quick_spline_region_selection_uses_kernel_and_is_read_only(qtbot: QtBot) -> None:
    from mycad.core.sketch import SplineEntity
    from mycad.geom.drawing_spline_regions import measure_planar_region_at

    editor = SketchEditorDialog(
        select_committed_entities=True, measure_planar_region=measure_planar_region_at
    )
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    spline = SplineEntity(uuid4().hex, ((0, 0), (0, 10), (10, 10), (10, 0)))
    line = LineEntity(uuid4().hex, (10, 0), (0, 0))
    assert canvas.replace_draft_entities((spline, line))
    history = canvas.history_position
    bar = editor.drawing_command_bar.input
    for value in ("MEASUREGEOM", "Q"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 2)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=20000)
    assert "面积 60" in editor.drawing_command_bar.status.text()
    assert "周长 30" in editor.drawing_command_bar.status.text()
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((5, 2)),
    )
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 0, timeout=20000)
    assert canvas.entities == [spline, line] and canvas.history_position == history


def test_main_window_wires_spline_quick_region_kernel(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import SplineEntity
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    spline = SplineEntity(uuid4().hex, ((0, 0), (0, 10), (10, 10), (10, 0)))
    line = LineEntity(uuid4().hex, (10, 0), (0, 0))
    assert editor.canvas.replace_draft_entities((spline, line))
    bar = editor.drawing_command_bar.input
    for value in ("MEASUREGEOM", "Q"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 2))
    )
    qtbot.waitUntil(lambda: len(editor.canvas.quick_measure_regions) == 1, timeout=20000)
    assert "面积 60" in editor.drawing_command_bar.status.text()


def test_spline_quick_region_discards_result_when_drawing_changes(qtbot: QtBot) -> None:
    from threading import Event

    from mycad.core.drawing_quick_regions import SampledMeasuredRegion
    from mycad.core.sketch import Point2D, SketchEntity, SplineEntity

    started, release = Event(), Event()

    def delayed(entities: tuple[SketchEntity, ...], point: Point2D) -> SampledMeasuredRegion | None:
        started.set()
        if not release.wait(5):
            raise ValueError("timeout")
        return SampledMeasuredRegion(((0, 0), (5, 5), (10, 0)), (), 60, 30)

    editor = SketchEditorDialog(select_committed_entities=True, measure_planar_region=delayed)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    spline = SplineEntity(uuid4().hex, ((0, 0), (0, 10), (10, 10), (10, 0)))
    assert canvas.replace_draft_entities((spline,))
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 2)))
    qtbot.waitUntil(started.is_set, timeout=10000)
    assert canvas.replace_draft_entities(())
    release.set()
    qtbot.waitUntil(lambda: QThreadPool.globalInstance().activeThreadCount() == 0, timeout=10000)
    QApplication.processEvents()
    assert canvas.quick_measure_regions == ()
    assert "面积 60" not in bar.status.text()


def test_quick_region_totals_remain_visible_while_moving_for_shift_selection(qtbot: QtBot) -> None:
    from mycad.core.sketch import RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (-10, -5), (10, 5))
    assert canvas.replace_draft_entities((rectangle,))
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    QTest.mouseMove(canvas, canvas.local_to_screen((4, 0)))
    assert len(canvas.quick_measure_regions) == 1
    assert "面积 200" in bar.status.text()
    assert "周长 60" in bar.status.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, 0)))
    assert "未找到唯一封闭区域" in bar.status.text()
    QTest.mouseMove(canvas, canvas.local_to_screen((5, 0)))
    assert "面积 200" in bar.status.text()


def test_quick_region_tooltip_follows_pointer_and_clears(qtbot: QtBot) -> None:
    from mycad.core.sketch import RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    assert canvas.replace_draft_entities((RectangleEntity(uuid4().hex, (-10, -5), (10, 5)),))
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    click = canvas.local_to_screen((0, 0))
    QTest.mouseMove(canvas, click)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=click)
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    tip = bar.quick_region_tooltip
    assert tip.isVisible()
    assert "面积 200" in tip.text() and "周长 60" in tip.text()
    before = tip.pos()
    QTest.mouseMove(canvas, canvas.local_to_screen((5, 0)))
    assert tip.pos() != before
    assert canvas.rect().contains(tip.geometry())
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not tip.isVisible()


def test_quick_region_tooltip_updates_shift_totals_and_hides_on_leave(qtbot: QtBot) -> None:
    from mycad.core.sketch import RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    first = RectangleEntity(uuid4().hex, (-20, -5), (-10, 5))
    second = RectangleEntity(uuid4().hex, (10, -5), (14, 5))
    assert canvas.replace_draft_entities((first, second))
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-15, 0)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 100" in bar.quick_region_tooltip.text()
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((12, 0)),
    )
    assert len(canvas.quick_measure_regions) == 2
    assert "面积 140" in bar.quick_region_tooltip.text()
    QApplication.sendEvent(canvas, QEvent(QEvent.Type.Leave))
    assert not bar.quick_region_tooltip.isVisible()
    QTest.mouseMove(canvas, canvas.local_to_screen((13, 0)))
    assert bar.quick_region_tooltip.isVisible()
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((-15, 0)),
    )
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((12, 0)),
    )
    assert not canvas.quick_measure_regions
    assert not bar.quick_region_tooltip.isVisible()


def test_quick_region_clears_when_document_layer_is_hidden(qtbot: QtBot) -> None:
    from dataclasses import replace

    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    layers = SketchLayerTable().add(SketchLayer("待隐藏"))
    editor.set_document_layers(layers, "0")
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (-10, -5), (10, 5), layer_name="待隐藏")
    assert canvas.replace_draft_entities((rectangle,))
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    assert "面积 200" in bar.status.text()
    editor.set_document_layers(layers.replace(replace(layers.get("待隐藏"), visible=False)), "0")
    assert not canvas.visible_snap_entities()
    assert not canvas.quick_measure_regions
    assert not bar.quick_region_tooltip.isVisible()
    assert "面积 200" not in bar.status.text()


def test_quick_region_clears_when_saved_background_is_replaced(qtbot: QtBot) -> None:
    from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (-10, -5), (10, 5))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    canvas.set_background_sketches((sketch,), WorkPlaneFrame.xy())
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    qtbot.waitUntil(lambda: len(canvas.quick_measure_regions) == 1, timeout=10000)
    canvas.set_background_sketches((), WorkPlaneFrame.xy())
    assert not canvas.quick_measure_regions
    assert not bar.quick_region_tooltip.isVisible()
    assert "面积 200" not in bar.status.text()


def test_quick_region_ignores_pending_result_after_layer_is_hidden(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from dataclasses import replace
    from threading import Event

    from mycad.core.sketch import CircleEntity, RectangleEntity
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui import drawing2d_command_bar as command_module

    started, release = Event(), Event()
    original = command_module.build_quick_regions

    def delayed(
        lines: tuple[LineEntity, ...], circles: tuple[CircleEntity, ...]
    ) -> tuple[LinearRegion, ...]:
        started.set()
        if not release.wait(5):
            raise ValueError("timeout")
        return original(lines, circles)

    monkeypatch.setattr(command_module, "build_quick_regions", delayed)
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    layers = SketchLayerTable().add(SketchLayer("待隐藏"))
    editor.set_document_layers(layers, "0")
    canvas = editor.canvas
    assert canvas.replace_draft_entities(
        (RectangleEntity(uuid4().hex, (-10, -5), (10, 5), layer_name="待隐藏"),)
    )
    bar = editor.drawing_command_bar
    for value in ("MEASUREGEOM", "Q"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    qtbot.waitUntil(started.is_set, timeout=10000)
    editor.set_document_layers(layers.replace(replace(layers.get("待隐藏"), visible=False)), "0")
    release.set()
    qtbot.waitUntil(lambda: QThreadPool.globalInstance().activeThreadCount() == 0, timeout=10000)
    QApplication.processEvents()
    assert not canvas.quick_measure_regions
    assert "面积 200" not in bar.status.text()
