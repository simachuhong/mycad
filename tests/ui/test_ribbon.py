# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Ribbon groups present the same actions as other application entry points."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QToolButton
from pytestqt.qtbot import QtBot

from mycad.ui.ribbon import RibbonGroup


def test_ribbon_group_reuses_actions_and_presents_primary_action(qtbot: QtBot) -> None:
    primary = QAction("拉伸")
    secondary = QAction("旋转")
    group = RibbonGroup("特征", (primary,), (secondary,))
    qtbot.addWidget(group)
    buttons = group.findChildren(QToolButton)
    main = next(button for button in buttons if button.defaultAction() is primary)
    small = next(button for button in buttons if button.defaultAction() is secondary)
    assert main.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon
    assert small.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    primary.setEnabled(False)
    assert not main.isEnabled()
    assert any(label.text() == "特征" for label in group.findChildren(QLabel))


def test_part_ribbon_groups_real_actions_without_extra_feature_pages(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    assert [window.part_ribbon.tabText(i) for i in range(window.part_ribbon.count())] == [
        "主页",
        "草图",
        "检查",
        "工具",
        "视图",
    ]
    buttons = window.part_ribbon.findChildren(QToolButton)
    extrude = window.action_catalog.get("feature.extrude")
    assert any(button.defaultAction() is extrude for button in buttons)
    assert any(button.defaultAction() is window.act_fit_view for button in buttons)
    assert any(button.defaultAction() is window.act_measure for button in buttons)


def test_part_structure_tree_moves_to_left_and_stays_hidden_in_2d(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("part")
    assert window.right_panel is not None
    assert window.left_dock.isAncestorOf(window.right_panel.structure_tree)
    window.new_session_document("sketch")
    assert not window.left_dock.isVisible()
    assert not window.part_sketch_entry_toolbar.isVisible()
    assert not window.act_measure.isEnabled()


def test_document_tabs_switch_same_kind_documents_and_guard_draft(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    first = window.new_session_document("part")
    second = window.new_session_document("part")
    assert window.document_tab_bar.count() == 2
    assert window.document_tab_bar.tabData(0) == first.loaded.document.document_id
    assert window.document_tab_bar.tabData(1) == second.loaded.document.document_id
    window.document_tab_bar.setCurrentIndex(0)
    assert session.active is first
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    window.document_tab_bar.setCurrentIndex(1)
    assert session.active is first
    assert window.document_tab_bar.currentIndex() == 0
    assert task.has_draft
    window.document_tab_bar.tabCloseRequested.emit(1)
    assert session.documents == (first, second)
    assert session.active is first
    assert task.has_draft
    task.reject()


def test_compact_quick_access_keeps_model_actions_reachable_in_ribbon(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("part")
    quick = [action.text() for action in window.main_toolbar.actions() if action.text()]
    assert quick[:5] == ["新建", "打开", "保存", "撤销", "重做"]
    ribbon_actions = {
        button.defaultAction() for button in window.part_ribbon.findChildren(QToolButton)
    }
    model_actions = {
        action for action in window.modeling_toolbar.actions() if not action.isSeparator()
    }
    assert model_actions <= ribbon_actions
    assert window.modeling_toolbar.isHidden()


def test_measure_action_opens_real_measurement_panel(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("part")
    panel = window.right_panel
    assert panel is not None
    assert window.act_measure.isEnabled()
    window.act_measure.trigger()
    assert window.right_dock.isVisible()
    assert panel.tabs.tabText(panel.tabs.currentIndex()) == "测量"
    assert panel.tabs.isTabEnabled(panel.tabs.currentIndex())


def test_application_button_opens_the_existing_file_menu(qtbot: QtBot) -> None:
    from mycad.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.application_button.menu() is window.menu_file
    assert window.application_button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup


def test_narrow_ribbon_keeps_visible_group_title_unclipped(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1024, 768)
    window.show()
    window.new_session_document("part")
    qtbot.wait(50)
    title = next(
        label for label in window.part_ribbon.findChildren(QLabel) if label.text() == "选择"
    )
    assert title.isVisible()
    assert title.visibleRegion().boundingRect().height() >= title.height()


def test_worker_error_history_retains_complete_multiline_message(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(window)
    unit = window.execution_unit
    assert unit is not None

    def fail() -> object:
        raise ValueError("第一行错误\n用于修复的详细信息")

    assert unit.submit(fail, operation="test-error", session_id=unit.session_id)
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert "第一行错误" in window.information_tab.output.toPlainText()
    assert "用于修复的详细信息" in window.information_tab.output.toPlainText()


def test_document_tab_remains_on_active_document_while_switch_is_queued(qtbot: QtBot) -> None:
    from threading import Event

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    first = window.new_session_document("part")
    second = window.new_session_document("part")
    unit = window.execution_unit
    assert unit is not None
    release = Event()
    try:
        assert unit.submit(
            lambda: release.wait(15),
            operation="test",
            session_id=unit.session_id,
            on_complete=lambda _result: None,
        )
        window.document_tab_bar.setCurrentIndex(0)
        assert session.active is second
        assert window.document_tab_bar.currentIndex() == 1
        release.set()
        qtbot.waitUntil(lambda: session.active is first)
        assert window.document_tab_bar.currentIndex() == 0
    finally:
        release.set()
