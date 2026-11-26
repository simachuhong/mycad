# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Open existing drawing panels from the command line."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.ui.sketch_editor import SketchEditorDialog


def test_idle_right_click_repeats_previous_drawing_command(qtbot: QtBot) -> None:
    from PySide6.QtCore import QCoreApplication, QPoint
    from PySide6.QtGui import QContextMenuEvent

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    command.setText("LINE")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.tool == "直线"
    assert canvas.set_tool("选择元素")
    assert canvas.tool == "选择元素"
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
    assert canvas.tool == "直线"
    point = QPoint(25, 25)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, canvas.mapToGlobal(point))
    QCoreApplication.sendEvent(canvas, event)
    assert event.isAccepted()


def test_idle_right_click_without_previous_command_prompts_for_command(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(editor.canvas, Qt.MouseButton.RightButton)
    assert "请输入命令" in editor.drawing_command_bar.status.text()


def test_idle_right_click_repeats_zoom_after_completing_it(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    command.setText("ZOOM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    command.setText("2X")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(editor.canvas, Qt.MouseButton.RightButton)
    assert "ZOOM" in editor.drawing_command_bar.status.text()
    assert "指定窗口" in editor.drawing_command_bar.status.text()


def test_command_input_starts_on_new_line_after_previous_message(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar
    field = command.input
    field.setText("ZOOM")
    QTest.keyClick(field, Qt.Key.Key_Return)
    QTest.keyClicks(field, "2X")
    lines = field.toPlainText().splitlines()
    assert lines[-1] == "命令: 2X"
    assert "ZOOM" in "\n".join(lines[:-1])
    command.status.setText("请选择下一点。")
    lines = field.toPlainText().splitlines()
    assert lines[-2:] == ["请选择下一点。", "命令: 2X"]
    assert field.text() == "2X"


def test_layer_and_properties_commands_open_existing_panels(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar.input
    bar.setText("LAYER")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.active_layer_manager is not None
    assert editor.active_layer_manager.isVisible()
    editor.active_layer_manager.close()
    editor.parameter_dock.hide()
    bar.setText("PROPERTIES")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.parameter_dock.isVisible()
    assert editor.parameter_tabs.tabText(editor.parameter_tabs.currentIndex()) == "特性"


def test_options_command_opens_main_window_system_settings(qtbot: QtBot) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from mycad import app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow
    from mycad.ui.preferences import CursorSettingsDialog

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    opened: list[bool] = []

    def close_options() -> None:
        dialog = QApplication.activeModalWidget()
        opened.append(isinstance(dialog, CursorSettingsDialog))
        if isinstance(dialog, CursorSettingsDialog):
            dialog.reject()

    QTimer.singleShot(100, close_options)
    bar = editor.drawing_command_bar.input
    bar.setText("OPTIONS")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert opened == [True]


def test_zoom_and_pan_commands_change_only_view(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    bar = editor.drawing_command_bar.input
    original = canvas.local_to_screen((0.0, 0.0))
    bar.setText("PAN")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    bar.setText("0,0")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    bar.setText("5,0")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    moved = canvas.local_to_screen((0.0, 0.0))
    assert moved.x() > original.x()
    before = canvas.local_to_screen((1.0, 0.0)).x() - moved.x()
    bar.setText("ZOOM")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    bar.setText("2X")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    after = canvas.local_to_screen((1.0, 0.0)).x() - canvas.local_to_screen((0.0, 0.0)).x()
    assert after > before
    assert not canvas.entities


def test_pan_mouse_points_and_cancel_preserve_drawing(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    bar = editor.drawing_command_bar.input
    before = canvas.local_to_screen((0.0, 0.0))
    bar.setText("PAN")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert canvas.local_to_screen((0.0, 0.0)).x() > before.x()
    assert not canvas.entities
    bar.setText("ZOOM")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.keyClick(bar, Qt.Key.Key_Escape)
    assert not canvas.entities


def test_zoom_window_coordinates_fit_and_preserve_drawing(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10, 10), (30, 20))
    assert canvas.replace_draft_entities((line,))
    before_history = canvas.history_position
    bar = editor.drawing_command_bar.input
    for command in ("ZOOM", "W", "10,10", "@20,10"):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    first, second = canvas.local_to_screen((10, 10)), canvas.local_to_screen((30, 20))
    assert 0 <= first.x() <= canvas.width() and 0 <= second.x() <= canvas.width()
    assert 0 <= first.y() <= canvas.height() and 0 <= second.y() <= canvas.height()
    assert abs((first.x() + second.x()) / 2 - canvas.width() / 2) <= 1
    assert abs((first.y() + second.y()) / 2 - canvas.height() / 2) <= 1
    assert abs(first.x() - second.x()) > 100
    assert canvas.entities == [line]
    assert canvas.history_position == before_history


def test_zoom_window_mouse_and_invalid_second_corner(qtbot: QtBot) -> None:
    from PySide6.QtCore import QPointF

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    bar = editor.drawing_command_bar
    original = canvas.local_to_screen((0, 0))
    bar.input.setText("ZOOM")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    first = canvas.local_to_screen((10, 10))
    second = canvas.local_to_screen((30, 20))
    p1 = canvas.screen_to_local(QPointF(first))
    p2 = canvas.screen_to_local(QPointF(second))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=first)
    bar.input.setText("10,10")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "窗口" in bar.status.text()
    assert canvas.local_to_screen((0, 0)) == original
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=second)
    center = canvas.local_to_screen(((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2))
    assert abs(center.x() - canvas.width() / 2) <= 1
    assert abs(center.y() - canvas.height() / 2) <= 1
    assert not canvas.entities


def test_zoom_invalid_first_coordinate_can_still_choose_scale(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    bar = editor.drawing_command_bar
    previous = canvas.view_scale
    for command in ("ZOOM", "@1,1", "2X"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.view_scale == previous * 2
    assert "缩放完成" in bar.status.text()


def test_zoom_window_click_on_dimension_is_view_corner(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        30,
        "mm",
        driving=False,
        position_mm=(15, 10),
    )
    canvas.entities = [line]
    canvas.constraints = [dimension]
    canvas.set_tool("选择元素")
    canvas.changed.emit()
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    label = layout.label.toPoint()
    bar = editor.drawing_command_bar
    bar.input.setText("ZOOM")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=label)
    assert "对角点" in bar.status.text()
    assert not canvas.selected_constraint_ids
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        pos=label + canvas.local_to_screen((5, 5)) - canvas.local_to_screen((0, 0)),
    )
    assert "窗口缩放完成" in bar.status.text()
    assert canvas.entities == [line]
    assert canvas.constraints == [dimension]
    canvas.fit_view()
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert canvas.selected_constraint_ids == {dimension.constraint_id}


def test_zoom_previous_restores_command_views_without_changing_drawing(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    bar = editor.drawing_command_bar

    def view() -> tuple[float, object]:
        return canvas.view_scale, canvas.local_to_screen((0, 0))

    def submit(*commands: str) -> None:
        for command in commands:
            bar.input.setText(command)
            QTest.keyClick(bar.input, Qt.Key.Key_Return)

    original = view()
    submit("PAN", "0,0", "5,3")
    panned = view()
    submit("ZOOM", "2X")
    assert view() != panned
    submit("ZOOM", "P")
    assert view() == panned
    submit("ZOOM", "PREVIOUS")
    assert view() == original
    submit("ZOOM", "P")
    assert "上一视图" in bar.status.text()
    assert view() == original
    assert not canvas.entities
    assert canvas.history_position == 0


def test_zoom_previous_restores_wheel_and_whole_pan_gesture(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    bar = editor.drawing_command_bar

    def view() -> tuple[float, object]:
        return canvas.view_scale, canvas.local_to_screen((0, 0))

    def previous() -> None:
        for command in ("ZOOM", "P"):
            bar.input.setText(command)
            QTest.keyClick(bar.input, Qt.Key.Key_Return)

    initial = view()
    position = QPointF(canvas.width() / 2, canvas.height() / 2)
    wheel = QWheelEvent(
        position,
        QPointF(canvas.mapToGlobal(position.toPoint())),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(canvas, wheel)
    zoomed = view()
    assert zoomed != initial
    QTest.mousePress(canvas, Qt.MouseButton.MiddleButton, pos=position.toPoint())
    for delta in (QPointF(20, 10), QPointF(40, 20)):
        end = position + delta
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
    assert view() != zoomed
    previous()
    assert view() == zoomed
    previous()
    assert view() == initial
    assert not canvas.entities


def test_zoom_previous_limits_history_and_ignores_noop(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    bar = editor.drawing_command_bar
    initial = canvas.local_to_screen((0, 0))

    def submit(*commands: str) -> None:
        for command in commands:
            bar.input.setText(command)
            QTest.keyClick(bar.input, Qt.Key.Key_Return)

    submit("ZOOM", "1X")
    submit("ZOOM", "P")
    assert "没有可恢复" in bar.status.text()
    for _ in range(11):
        submit("PAN", "0,0", "1,0")
    for _ in range(10):
        submit("ZOOM", "P")
    assert canvas.local_to_screen((0, 0)).x() == initial.x() + round(canvas.view_scale)
    submit("ZOOM", "P")
    assert "没有可恢复" in bar.status.text()


def test_zoom_previous_ignores_pan_drag_returning_to_start(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    bar = editor.drawing_command_bar
    original_scale = canvas.view_scale
    for command in ("ZOOM", "2X"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    start = QPointF(canvas.width() / 2, canvas.height() / 2)
    QTest.mousePress(canvas, Qt.MouseButton.MiddleButton, pos=start.toPoint())
    for end in (start + QPointF(40, 20), start):
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            end,
            end,
            QPointF(canvas.mapToGlobal(end.toPoint())),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.MiddleButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(canvas, event)
    QTest.mouseRelease(canvas, Qt.MouseButton.MiddleButton, pos=start.toPoint())
    for command in ("ZOOM", "P"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.view_scale == original_scale


def test_zoom_previous_tracks_wheel_during_pan_in_order(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    bar = editor.drawing_command_bar

    def view() -> tuple[float, object]:
        return canvas.view_scale, canvas.local_to_screen((0, 0))

    def previous() -> None:
        for command in ("ZOOM", "P"):
            bar.input.setText(command)
            QTest.keyClick(bar.input, Qt.Key.Key_Return)

    start = QPointF(canvas.width() / 2, canvas.height() / 2)
    initial = view()
    panned = zoomed = initial
    QTest.mousePress(canvas, Qt.MouseButton.MiddleButton, pos=start.toPoint())
    for offset in (20, 40):
        position = start + QPointF(offset, 0)
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            position,
            QPointF(canvas.mapToGlobal(position.toPoint())),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.MiddleButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(canvas, move)
        if offset == 20:
            panned = view()
            wheel = QWheelEvent(
                position,
                QPointF(canvas.mapToGlobal(position.toPoint())),
                QPoint(),
                QPoint(0, 120),
                Qt.MouseButton.MiddleButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            QApplication.sendEvent(canvas, wheel)
            zoomed = view()
    QTest.mouseRelease(canvas, Qt.MouseButton.MiddleButton, pos=position.toPoint())
    previous()
    assert view() == zoomed
    previous()
    assert view() == panned
    previous()
    assert view() == initial


def test_zoom_window_preview_appears_and_cancel_clears(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    bar = editor.drawing_command_bar
    sample = canvas.local_to_screen((20, 15))
    ratio = canvas.devicePixelRatioF()

    def pixel() -> object:
        return (
            canvas.grab().toImage().pixelColor(round(sample.x() * ratio), round(sample.y() * ratio))
        )

    original = pixel()
    old_scale = canvas.view_scale
    for command in ("ZOOM", "0,0"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseMove(canvas, canvas.local_to_screen((40, 30)))
    assert pixel() != original
    assert canvas.view_scale == old_scale
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert pixel() == original
    assert not canvas.entities


def test_zoom_window_preview_tracks_pan_and_clears_on_leave_and_commit(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    bar = editor.drawing_command_bar
    for command in ("ZOOM", "0,0"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    end = canvas.local_to_screen((40, 30))
    QTest.mouseMove(canvas, end)
    QTest.mousePress(canvas, Qt.MouseButton.MiddleButton, pos=end)
    moved = QPointF(end.x() + 30, end.y() + 20)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        moved,
        moved,
        QPointF(canvas.mapToGlobal(moved.toPoint())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, event)
    QTest.mouseRelease(canvas, Qt.MouseButton.MiddleButton, pos=moved.toPoint())
    sample = canvas.local_to_screen((20, 15))
    ratio = canvas.devicePixelRatioF()

    def pixel() -> object:
        return (
            canvas.grab().toImage().pixelColor(round(sample.x() * ratio), round(sample.y() * ratio))
        )

    assert pixel() != Qt.GlobalColor.white
    QApplication.sendEvent(canvas, QEvent(QEvent.Type.Leave))
    assert pixel() == Qt.GlobalColor.white
    QTest.mouseMove(canvas, moved.toPoint())
    assert pixel() != Qt.GlobalColor.white
    bar.input.setText("40,30")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "窗口缩放完成" in bar.status.text()
    sample = canvas.local_to_screen((20, 15))
    assert pixel() == Qt.GlobalColor.white
    assert not canvas.entities


def test_zoom_window_preview_handles_far_coordinate(qtbot: QtBot) -> None:
    import math

    from PySide6.QtCore import QRectF

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    bar = editor.drawing_command_bar
    for command in ("ZOOM", "1e300,1e300"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseMove(canvas, canvas.rect().center())
    image = canvas.grab().toImage()
    assert not image.isNull()
    bar.input.setText("0,0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "窗口缩放完成" in bar.status.text()
    assert math.isfinite(canvas.view_scale) and canvas.view_scale > 0
    viewport = QRectF(canvas.rect()).adjusted(-1, -1, 1, 1)
    assert viewport.contains(canvas.local_to_screen_precise((0, 0)))
    assert viewport.contains(canvas.local_to_screen_precise((1e300, 1e300)))
    assert not canvas.grab().isNull()
    assert not canvas.entities


def test_pan_and_zoom_window_on_far_visible_block_remain_usable(qtbot: QtBot) -> None:
    from uuid import uuid4

    import pytest
    from PySide6.QtCore import QPointF

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas, bar = editor.canvas, editor.drawing_command_bar
    rectangle = RectangleEntity(uuid4().hex, (1e9, 1e9), (1e9 + 1, 1e9 + 2))
    definition = BlockDefinition(uuid4().hex, "Far", (rectangle,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 7), 30)
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    canvas.fit_view()
    entity = canvas.drawing_block_view().geometry[0].entity
    assert isinstance(entity, PolylineEntity)
    center = tuple(sum(point[axis] for point in entity.points_mm) / 4 for axis in (0, 1))
    tracked = (center[0], center[1])
    original = canvas.local_to_screen_precise(tracked)
    scale = canvas.view_scale

    def submit(*commands: str) -> None:
        for command in commands:
            bar.input.setText(command)
            QTest.keyClick(bar.input, Qt.Key.Key_Return)

    submit("PAN", "0,0", "1,0")
    assert "视图平移完成" in bar.status.text()
    panned = canvas.local_to_screen_precise(tracked)
    assert panned.x() - original.x() == pytest.approx(scale, abs=1e-4)
    left = min(point[0] for point in entity.points_mm) - 1
    right = max(point[0] for point in entity.points_mm) + 1
    bottom = min(point[1] for point in entity.points_mm) - 1
    top = max(point[1] for point in entity.points_mm) + 1
    submit("ZOOM", "W", f"{left!r},{bottom!r}", f"{right!r},{top!r}")
    assert "窗口缩放完成" in bar.status.text()
    assert canvas.rect().contains(canvas.local_to_screen(tracked))
    before = canvas.local_to_screen_precise(tracked)
    far_x, far_y = tracked[0] + 1e7, tracked[1] + 1e7
    submit("ZOOM", "W", f"{far_x!r},{far_y!r}", f"{far_x + 10!r},{far_y + 10!r}")
    assert "超出视图范围" in bar.status.text()
    assert canvas.local_to_screen_precise(tracked) == before
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    submit("PAN", "0,0", "1e300,0")
    assert "超出可用范围" in bar.status.text()
    assert canvas.local_to_screen_precise(tracked) == before
    assert canvas.history_position == 0 and not canvas.entities
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    center_model = canvas.screen_to_local(QPointF(canvas.width() / 2, canvas.height() / 2))
    assert canvas.pan_view_between((0, 0), center_model)
    centered_origin = canvas.local_to_screen_precise((0, 0))
    assert centered_origin.x() == pytest.approx(canvas.width() / 2, abs=1e-4)
    assert centered_origin.y() == pytest.approx(canvas.height() / 2, abs=1e-4)
