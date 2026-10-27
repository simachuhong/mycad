# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared compact consoles leave room for 2D drafting."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.app import build_app
from mycad.ui.main_window import MainWindow


def drawing_window(qtbot: QtBot) -> MainWindow:
    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    return window


def test_two_dimensional_console_is_a_collapsed_tab_strip(qtbot: QtBot) -> None:
    window = drawing_window(qtbot)
    tabs = window.bottom_tabs
    assert tabs is not None
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["信息", "CLI", "AI 对话", "计划"]
    assert window.bottom_dock.isVisible()
    assert not tabs.expanded
    qtbot.wait(20)
    assert window.bottom_dock.height() < 80
    draft = window.active_sketch_dialog()
    assert draft is not None
    assert draft.toolbar_host.statusBar().isHidden()
    QTest.mouseClick(
        tabs.tabBar(), Qt.MouseButton.LeftButton, pos=tabs.tabBar().tabRect(1).center()
    )
    assert tabs.expanded and tabs.currentWidget() is window.cli_tab
    qtbot.wait(20)
    assert 160 <= window.bottom_dock.height() < 330
    QTest.mouseClick(
        tabs.tabBar(), Qt.MouseButton.LeftButton, pos=tabs.tabBar().tabRect(1).center()
    )
    assert not tabs.expanded
    assert window.cli_tab is not None and not window.cli_tab.isVisible()
    window.act_show_cli.trigger()
    assert tabs.expanded


def test_drawing_messages_are_logged_without_cursor_spam(qtbot: QtBot) -> None:
    window = drawing_window(qtbot)
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.status_label.setText("请选择尺寸固定端")
    assert window.status_command.text() == "请选择尺寸固定端"
    assert "请选择尺寸固定端" in window.information_tab.output.toPlainText()
    before = window.information_tab.output.toPlainText()
    draft.status_label.setText("请选择尺寸固定端")
    draft.canvas.cursor_changed.emit(1.0, 2.0, "")
    draft.canvas.cursor_changed.emit(3.0, 4.0, "")
    assert window.information_tab.output.toPlainText() == before
    assert window.width() < 2000


def test_cli_and_ai_drafts_survive_workspace_switches(qtbot: QtBot) -> None:
    window = drawing_window(qtbot)
    cli, tabs = window.cli_tab, window.bottom_tabs
    assert cli is not None and tabs is not None
    cli.input.setText("history")
    window.ai_chat.input.setPlainText("把这条边设为 40 mm")
    window.act_show_ai.trigger()
    assert tabs.currentWidget() is window.ai_chat and tabs.expanded
    assert not window.ai_chat.send_button.isEnabled()
    assert "未连接" in window.ai_chat.connection_label.text()
    window.act_view_3d.trigger()
    window.act_view_2d.trigger()
    assert window.cli_tab is cli and cli.input.text() == "history"
    assert window.ai_chat.input.toPlainText() == "把这条边设为 40 mm"
    assert tabs.currentWidget() is window.ai_chat and tabs.expanded
    window.act_show_cli.trigger()
    assert cli.submit_line("history")
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert window.active_sketch_dialog() is not None


def test_cli_cannot_replace_document_with_unsubmitted_sketch(qtbot: QtBot) -> None:
    window = drawing_window(qtbot)
    draft, cli = window.active_sketch_dialog(), window.cli_tab
    assert draft is not None and cli is not None
    draft.canvas.add_coordinate_point((0, 0))
    draft.canvas.add_coordinate_point((20, 0))
    draft.canvas.end_line_chain()
    original = cli.current
    assert not cli.submit_line("new")
    assert cli.current is original and window.active_sketch_dialog() is draft
    assert len(draft.canvas.entities) == 1
    assert "草图尚未提交" in cli.output.toPlainText()
    assert cli.submit_line("history")
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)


def test_console_open_keeps_inline_dimension_escape(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = drawing_window(qtbot)
    draft, tabs = window.active_sketch_dialog(), window.bottom_tabs
    assert draft is not None and tabs is not None
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=30,
        unit="mm",
        axis="horizontal",
        position_mm=(15, -10),
    )
    draft.canvas.entities = [line]
    draft.canvas.constraints = [constraint]
    draft.canvas.changed.emit()
    for floating in (False, True):
        window.bottom_dock.setFloating(floating)
        for entry in ("tab", "cli-menu", "ai-menu", "information-menu", "plan-menu"):
            tabs.setCurrentWidget(window.information_tab)
            draft.dimensions.edit(draft.dimension_sources()[0], constraint)
            qtbot.waitUntil(draft.dimensions.value_editor.hasFocus)
            if entry == "tab":
                QTest.mouseClick(
                    tabs.tabBar(),
                    Qt.MouseButton.LeftButton,
                    pos=tabs.tabBar().tabRect(1).center(),
                )
            elif entry == "cli-menu":
                window.act_show_cli.trigger()
            elif entry == "ai-menu":
                window.act_show_ai.trigger()
            elif entry == "information-menu":
                window.act_show_information.trigger()
            else:
                window.act_view_plans.trigger()
            qtbot.waitUntil(draft.dimensions.value_editor.hasFocus, timeout=500)
            focused = QApplication.focusWidget()
            assert focused is not None
            QTest.keyClick(focused, Qt.Key.Key_Escape)
            assert draft.dimensions.candidate is None
            assert not draft.dimensions.inline_box.isVisible()
            assert draft.canvas.constraints == [constraint]
