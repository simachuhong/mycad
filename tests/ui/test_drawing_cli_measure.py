# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Interactive distance measurement in the drawing console."""

from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import LineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def test_dist_coordinates_reports_result_without_changing_geometry(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    assert editor.canvas.replace_draft_entities((line,))
    bar = editor.drawing_command_bar
    for command in ("DIST", "0,0", "@3,4"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "距离：5" in bar.input.toPlainText()
    assert "ΔX：3" in bar.input.toPlainText()
    assert "ΔY：4" in bar.input.toPlainText()
    assert editor.canvas.entities == [line]
    assert editor.canvas.undo_last_operation()
    assert not editor.canvas.entities


def test_dist_mouse_snap_repeat_and_cancel(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    bar = editor.drawing_command_bar
    bar.input.setText("DI")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.5, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((9.5, 0)))
    assert "距离：10" in bar.input.toPlainText()
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "指定第一点" in bar.status.text()
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    bar.input.setText("LINE")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.tool == "直线"
    assert canvas.entities == [line]


def test_area_coordinate_polygon_undo_and_self_intersection(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for command in ("AREA", "0,0", "4,0", "4,3", "1,1", "U", "0,3", ""):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "面积：12" in bar.input.toPlainText()
    assert "周长：14" in bar.input.toPlainText()
    assert not editor.canvas.entities
    for command in ("AREA", "0,0", "4,3", "0,3", "4,0", ""):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "自交" in bar.status.text()
    assert not editor.canvas.entities


def test_area_mouse_and_right_click_finishes(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    bar = editor.drawing_command_bar
    bar.input.setText("AREA")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    for point in ((0, 0), (10, 0), (10, 10), (0, 10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=canvas.local_to_screen((0, 10)))
    assert "面积：100" in bar.input.toPlainText()
    assert "周长：40" in bar.input.toPlainText()
    assert not canvas.entities


def test_area_object_circle_and_rectangle(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    rectangle = RectangleEntity(uuid4().hex, (20, 0), (24, 3))
    assert canvas.replace_draft_entities((circle, rectangle))
    bar = editor.drawing_command_bar
    for command in ("AREA", "O"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert "面积：78.5398" in bar.input.toPlainText()
    for command in ("AREA", "O"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((22, 0)))
    assert "面积：12" in bar.input.toPlainText()
    assert canvas.entities == [circle, rectangle]


def test_area_object_closed_polyline(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    assert canvas.replace_draft_entities((line,))
    bar = editor.drawing_command_bar
    for command in ("AREA", "O"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert "面积：100" in bar.input.toPlainText()
    assert "周长：40" in bar.input.toPlainText()
    assert canvas.entities == [line]


def test_area_object_curved_polyline(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    entity = PolylineEntity(
        uuid4().hex,
        ((-10, 0), (10, 0), (10, 10), (-10, 10)),
        True,
        bulges=(1, 0, 0, 0),
    )
    assert canvas.replace_draft_entities((entity,))
    bar = editor.drawing_command_bar
    for command in ("AREA", "O"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, -10)))
    assert "面积：357.08" in bar.input.toPlainText()
    assert "周长：71.4159" in bar.input.toPlainText()
    assert canvas.entities == [entity]


def test_area_object_rejects_self_touching_curved_polyline(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    entity = PolylineEntity(
        uuid4().hex,
        ((-10, 0), (10, 0), (10, 10), (-10, 10)),
        True,
        bulges=(-1, 0, 0, 0),
    )
    assert canvas.replace_draft_entities((entity,))
    bar = editor.drawing_command_bar
    for command in ("AREA", "O"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-10, 5)))
    assert "自交" in bar.status.text()
    assert canvas.entities == [entity]


def test_measuregeom_radius_and_three_point_angle(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    assert canvas.replace_draft_entities((circle,))
    bar = editor.drawing_command_bar
    for command in ("MEASUREGEOM", "R"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert "半径：5" in bar.input.toPlainText()
    assert "直径：10" in bar.input.toPlainText()
    for command in ("MEASUREGEOM", "A", "0,0", "10,0", "0,10"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "夹角：90" in bar.input.toPlainText()
    assert canvas.entities == [circle]


def test_measuregeom_angle_retries_vertex_and_routes_area(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for command in ("MEA", "A", "0,0", "0,0"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "不能与顶点重合" in bar.status.text()
    for command in ("10,0", "0,10"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "夹角：90" in bar.input.toPlainText()
    for command in ("MEASUREGEOM", "AR", "0,0", "4,0", "0,3", ""):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "面积：6" in bar.input.toPlainText()
    assert not editor.canvas.entities


def test_measuregeom_rejects_line_then_measures_arc(qtbot: QtBot) -> None:
    from mycad.core.sketch import ArcEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (-20, 0), (-10, 0))
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 90)
    assert canvas.replace_draft_entities((line, arc))
    bar = editor.drawing_command_bar
    for command in ("MEA", "R"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-15, 0)))
    assert "圆或圆弧" in bar.status.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    assert "半径：10" in bar.input.toPlainText()
    assert canvas.entities == [line, arc]


@pytest.mark.parametrize("kind", ["lines", "arc", "circle", "polyline"])
def test_measuregeom_angle_from_objects(qtbot: QtBot, kind: str) -> None:
    from mycad.core.sketch import ArcEntity, CircleEntity, PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    if kind == "lines":
        entities = (
            LineEntity(uuid4().hex, (0, 0), (10, 0)),
            LineEntity(uuid4().hex, (10, 0), (10, 10)),
        )
        picks = ("5,0", "10,5")
    elif kind == "arc":
        entities = (ArcEntity(uuid4().hex, (0, 0), 5, 0, 90),)
        picks = ("3.5355339,3.5355339",)
    elif kind == "circle":
        entities = (CircleEntity(uuid4().hex, (0, 0), 5),)
        picks = ("5,0", "0,5")
    else:
        entities = (PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), False),)
        picks = ("5,0", "10,5")
    canvas = editor.canvas
    assert canvas.replace_draft_entities(entities)
    bar = editor.drawing_command_bar
    for command in ("MEASUREGEOM", "A", "O", *picks):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "夹角：90" in bar.input.toPlainText()
    assert tuple(canvas.entities) == entities


def test_measuregeom_angle_mouse_rejects_same_line_then_measures_parallel(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (10, 10), (0, 10))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((first, second))
    bar = editor.drawing_command_bar
    for command in ("MEASUREGEOM", "A", "O"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert "另一条" in bar.status.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 10)))
    assert "夹角：0" in bar.input.toPlainText()
    assert canvas.entities == [first, second]


def test_measuregeom_angle_rejects_changed_first_object(qtbot: QtBot) -> None:
    from dataclasses import replace

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 10), (10, 10))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((line, second))
    bar = editor.drawing_command_bar
    for command in ("MEASUREGEOM", "A", "O", "5,0"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    changed = replace(line, end_mm=(12, 0))
    assert canvas.replace_draft_entities((changed, second))
    bar.input.setText("5,10")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "已变化" in bar.status.text()


def test_measuregeom_circle_angle_keeps_ray_direction(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    assert editor.canvas.replace_draft_entities((circle,))
    bar = editor.drawing_command_bar
    for command in ("MEASUREGEOM", "A", "O", "10,0", "-10,0"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "夹角：180" in bar.input.toPlainText()


def test_measuregeom_circle_angle_retries_center_pick(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    circle = CircleEntity(uuid4().hex, (0, 0), 0.1)
    assert editor.canvas.replace_draft_entities((circle,))
    bar = editor.drawing_command_bar
    for command in ("MEASUREGEOM", "A", "O", "0,0"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "圆心" in bar.status.text()
    for command in ("0.1,0", "0,1"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "夹角：90" in bar.input.toPlainText()


def test_measuregeom_circle_small_angle_retains_precision(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    assert editor.canvas.replace_draft_entities((CircleEntity(uuid4().hex, (0, 0), 10),))
    bar = editor.drawing_command_bar
    for command in ("MEASUREGEOM", "A", "O", "10,0", "10,0.00000001"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "夹角：5.72958e-08" in bar.input.toPlainText()


@pytest.mark.parametrize("command", ("DIST", "AREA", "MEASUREGEOM", "PAN", "ZOOM"))
def test_cancel_measurement_or_view_preserves_selection(qtbot: QtBot, command: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    bar.input.setText(command)
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert canvas.selected_entity_ids == {line.entity_id}
    assert canvas.entities == [line]


def test_starting_dimension_ends_pending_measurement(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    bar.input.setText("DIST")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    editor.dimensions.start("linear")
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    bar.input.setText("LINE")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.tool == "直线"


def test_starting_move_ends_pending_measurement(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    bar.input.setText("DIST")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    editor.transform_buttons["move"].click()
    for coordinate in ("0,0", "3,4"):
        bar.input.setText(coordinate)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].start_mm == (3, 4)


def test_area_add_subtract_points_and_objects(qtbot: QtBot) -> None:
    from mycad.core.sketch import RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (20, 0), (24, 3))
    assert canvas.replace_draft_entities((rectangle,))
    before = canvas.history_position
    bar = editor.drawing_command_bar
    for command in ("AREA", "A", "0,0", "4,0", "4,3", "0,3", ""):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "总面积：12" in bar.status.text()
    for command in ("S", "O"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((22, 0)))
    assert "总面积：0" in bar.status.text()
    assert "总周长：0" in bar.status.text()
    for command in ("", ""):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == [rectangle]
    assert canvas.history_position == before
    bar.input.setText("LINE")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.tool == "直线"


def test_area_add_mode_repeats_object_picks_and_cancel_resets_total(qtbot: QtBot) -> None:
    from mycad.core.sketch import RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = RectangleEntity(uuid4().hex, (0, 0), (4, 3))
    second = RectangleEntity(uuid4().hex, (20, 0), (22, 2))
    assert canvas.replace_draft_entities((first, second))
    bar = editor.drawing_command_bar
    for command in ("AREA", "ADD", "O"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    for point in ((2, 0), (21, 0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert "总面积：16" in bar.status.text()
    assert "总周长：22" in bar.status.text()
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    for command in ("AREA", "A", "0,0", "1,0", "1,1", ""):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "总面积：0.5" in bar.status.text()
    assert canvas.entities == [first, second]


def test_area_accumulation_rejects_invalid_object_and_continues(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    invalid = PolylineEntity(
        uuid4().hex, ((-10, 0), (10, 0), (10, 10), (-10, 10)), True, bulges=(-1, 0, 0, 0)
    )
    valid = RectangleEntity(uuid4().hex, (20, 0), (24, 3))
    assert canvas.replace_draft_entities((invalid, valid))
    bar = editor.drawing_command_bar
    for command in ("AREA", "A", "O"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-10, 5)))
    assert "自交" in bar.status.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((22, 0)))
    assert "总面积：12" in bar.status.text()
    assert canvas.entities == [invalid, valid]


def test_area_accumulation_offers_context_completion(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    bar.input.setText("AREA")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("AD")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "ADD"
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("O")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("SU")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "SUBTRACT"
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "扣减" in bar.status.text()


def test_area_accumulation_preserves_small_area_after_large_cancellation(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    commands = (
        "AREA",
        "A",
        "0,0",
        "100000000,0",
        "100000000,100000000",
        "0,100000000",
        "",
        "0,0",
        "1,0",
        "1,1",
        "0,1",
        "",
        "S",
        "0,0",
        "100000000,0",
        "100000000,100000000",
        "0,100000000",
        "",
    )
    for command in commands:
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "总面积：1 mm²" in bar.status.text()
    assert "总周长：4 mm" in bar.status.text()


def test_area_point_preview_is_visible_and_clears_on_cancel(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    bar = editor.drawing_command_bar
    sample = canvas.local_to_screen((20, 15))
    ratio = canvas.devicePixelRatioF()
    before = (
        canvas.grab().toImage().pixelColor(round(sample.x() * ratio), round(sample.y() * ratio))
    )
    for command in ("AREA", "A", "0,0", "40,0", "40,30", "0,30"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    preview = (
        canvas.grab().toImage().pixelColor(round(sample.x() * ratio), round(sample.y() * ratio))
    )
    assert preview != before
    assert preview.green() > preview.red()
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    cleared = (
        canvas.grab().toImage().pixelColor(round(sample.x() * ratio), round(sample.y() * ratio))
    )
    assert cleared == before
    assert not canvas.entities


def test_area_cursor_preview_subtract_undo_and_finish(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    canvas.set_snapping_enabled(False)
    bar = editor.drawing_command_bar
    sample = canvas.local_to_screen((10, 15))
    ratio = canvas.devicePixelRatioF()

    def pixel() -> object:
        return (
            canvas.grab().toImage().pixelColor(round(sample.x() * ratio), round(sample.y() * ratio))
        )

    before = pixel()
    for command in ("AREA", "S", "0,0", "40,0", "40,30"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseMove(canvas, canvas.local_to_screen((0, 30)))
    color = canvas.grab().toImage().pixelColor(round(sample.x() * ratio), round(sample.y() * ratio))
    assert color.red() > color.green()
    bar.input.setText("U")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert pixel() == before
    for command in ("40,30", "0,30", ""):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert pixel() == before
    assert "总面积：-1200" in bar.status.text()
    assert not canvas.entities


def test_area_preview_removes_cursor_when_pointer_leaves_canvas(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    canvas.set_snapping_enabled(False)
    bar = editor.drawing_command_bar
    sample = canvas.local_to_screen((25, 5))
    ratio = canvas.devicePixelRatioF()

    def pixel() -> object:
        return (
            canvas.grab().toImage().pixelColor(round(sample.x() * ratio), round(sample.y() * ratio))
        )

    before = pixel()
    for command in ("AREA", "0,0", "40,0"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseMove(canvas, canvas.local_to_screen((40, 30)))
    assert pixel() != before
    QApplication.sendEvent(canvas, QEvent(QEvent.Type.Leave))
    assert pixel() == before
    assert not canvas.entities


def test_area_preview_updates_after_middle_button_pan(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_grid_visible(False)
    bar = editor.drawing_command_bar
    for command in ("AREA", "0,0", "40,0"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    start = canvas.local_to_screen((40, 30))
    end = QPointF(start.x() + 50, start.y() + 20)
    QTest.mousePress(canvas, Qt.MouseButton.MiddleButton, pos=start)
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        end,
        end,
        QPointF(canvas.mapToGlobal(end.toPoint())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, move)
    QTest.mouseRelease(canvas, Qt.MouseButton.MiddleButton, pos=end.toPoint())
    image = canvas.grab().toImage()
    ratio = canvas.devicePixelRatioF()
    inside = canvas.local_to_screen((20, 5))
    outside = canvas.local_to_screen((44, 20))
    a = image.pixelColor(round(inside.x() * ratio), round(inside.y() * ratio))
    b = image.pixelColor(round(outside.x() * ratio), round(outside.y() * ratio))
    assert a.green() > a.red()
    assert b.red() == b.green() == b.blue() == 255


def test_area_preview_handles_far_coordinate(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    bar = editor.drawing_command_bar
    for command in ("AREA", "1e300,1e300"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseMove(canvas, canvas.rect().center())
    assert not canvas.grab().toImage().isNull()
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.entities


@pytest.mark.parametrize("exponent", [9, 300])
def test_area_preview_clips_far_line_without_changing_direction(
    qtbot: QtBot, exponent: int
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    bar = editor.drawing_command_bar
    for command in (
        "AREA",
        f"-1e{exponent},-1e{exponent - 1}",
        f"1e{exponent},1e{exponent - 1}",
    ):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    point = canvas.local_to_screen((20, 2))
    image = canvas.grab().toImage()
    ratio = canvas.devicePixelRatioF()
    colors = [
        image.pixelColor(round((point.x() + dx) * ratio), round((point.y() + dy) * ratio))
        for dx in range(-4, 5)
        for dy in range(-4, 5)
    ]
    assert any(color.green() > color.red() + 10 for color in colors)
    assert not canvas.entities


def test_area_preview_clips_far_polygon_without_changing_fill(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    bar = editor.drawing_command_bar
    for command in ("AREA", "-1e9,-1e8", "1e9,1e8", "-1e9,1e8"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    image = canvas.grab().toImage()
    ratio = canvas.devicePixelRatioF()
    inside = canvas.local_to_screen((20, 6))
    outside = canvas.local_to_screen((20, -2))
    a = image.pixelColor(round(inside.x() * ratio), round(inside.y() * ratio))
    b = image.pixelColor(round(outside.x() * ratio), round(outside.y() * ratio))
    assert a.green() > a.red()
    assert b.red() == b.green() == b.blue() == 255


def test_measuregeom_radius_measures_polyline_arc_and_retries_ambiguous_pick(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    polyline = PolylineEntity(uuid4().hex, ((-10, 0), (10, 0), (20, 0)), bulges=(1, 0))
    assert canvas.replace_draft_entities((polyline,))
    before = canvas.history_position
    bar = editor.drawing_command_bar
    for command in ("MEASUREGEOM", "R", "10,0"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "不明确" in bar.status.text()
    bar.input.setText("15,0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "圆或圆弧" in bar.status.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, -10)))
    assert "半径：10" in bar.input.toPlainText()
    assert "直径：20" in bar.input.toPlainText()
    assert canvas.entities == [polyline]
    assert not canvas.selected_entity_ids
    assert canvas.history_position == before
