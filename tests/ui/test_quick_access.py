# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Environment-specific quick access preferences and shared action state."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from mycad.ui.quick_access import QuickAccessStore


def test_quick_access_store_separates_environments_and_preserves_empty(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "qat.ini"), QSettings.Format.IniFormat)
    store = QuickAccessStore(settings)
    defaults = ("file.new", "file.open", "file.save")
    store.save("part", ("file.save", "plugin.missing", "file.new"))
    store.save("drawing2d", ())
    assert store.load("part", defaults) == ("file.save", "plugin.missing", "file.new")
    assert store.load("drawing2d", defaults) == ()
    assert store.load("drawing", defaults) == defaults
    reopened = QuickAccessStore(QSettings(str(tmp_path / "qat.ini"), QSettings.Format.IniFormat))
    assert reopened.load("part", defaults) == ("file.save", "plugin.missing", "file.new")
    assert reopened.load("drawing2d", defaults) == ()


@pytest.mark.parametrize("broken", ["not json", '["file.save", "file.save"]', "[1]", "{}"])
def test_quick_access_store_invalid_preferences_fall_back_without_overwrite(
    tmp_path: Path, broken: str
) -> None:
    settings = QSettings(str(tmp_path / "qat.ini"), QSettings.Format.IniFormat)
    settings.setValue("quick-access/v1/part", broken)
    store = QuickAccessStore(settings)
    assert store.load("part", ("file.new",)) == ("file.new",)
    assert settings.value("quick-access/v1/part") == broken


def test_quick_access_reuses_actions_and_recovers_missing_plugin(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QToolBar

    from mycad.ui.action_catalog import ActionCatalog
    from mycad.ui.quick_access import QuickAccessController

    settings = QSettings(str(tmp_path / "qat.ini"), QSettings.Format.IniFormat)
    store = QuickAccessStore(settings)
    catalog = ActionCatalog()
    saved = QAction("保存")
    catalog.register("file.save", saved)
    toolbar = QToolBar()
    qtbot.addWidget(toolbar)
    controller = QuickAccessController(toolbar, catalog, store, defaults=("file.save",))
    controller.set_environment("part")
    controller.set_actions(("file.save", "plugin.action"))
    assert toolbar.actions()[0] is saved
    missing = toolbar.actions()[1]
    assert not missing.isEnabled() and "plugin.action" in missing.toolTip()
    saved.setEnabled(False)
    assert not toolbar.actions()[0].isEnabled()
    plugin = QAction("插件动作")
    catalog.register("plugin.action", plugin)
    assert toolbar.actions() == [saved, plugin]
    catalog.unregister("plugin.action")
    assert not toolbar.actions()[1].isEnabled()
    assert store.load("part", ()) == ("file.save", "plugin.action")


def test_quick_access_dialog_edits_order_without_writing_until_confirm(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from PySide6.QtGui import QAction

    from mycad.ui.action_catalog import ActionCatalog
    from mycad.ui.quick_access import QuickAccessDialog

    store = QuickAccessStore(QSettings(str(tmp_path / "qat.ini"), QSettings.Format.IniFormat))
    store.save("part", ("file.save", "plugin.missing"))
    catalog = ActionCatalog()
    catalog.register("file.save", QAction("保存"))
    catalog.register("file.open", QAction("打开"))
    dialog = QuickAccessDialog(catalog, store.load("part", ()))
    qtbot.addWidget(dialog)
    dialog.available.setCurrentIndex(dialog.available.findData("file.open"))
    dialog.add_button.click()
    dialog.selected.setCurrentRow(2)
    dialog.up_button.click()
    assert dialog.identities() == ("file.save", "file.open", "plugin.missing")
    dialog.selected.setCurrentRow(0)
    dialog.remove_button.click()
    assert dialog.identities() == ("file.open", "plugin.missing")
    dialog.reject()
    assert store.load("part", ()) == ("file.save", "plugin.missing")


def test_main_window_quick_access_switches_and_remembers_environments(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    part = window.new_session_document("part")
    assert window.quick_access.environment == "part"
    window.quick_access.set_actions(("file.save", "edit.undo"))
    sketch = window.new_session_document("sketch")
    assert window.quick_access.environment == "drawing2d"
    window.quick_access.set_actions(("file.open",))
    window.activate_session_document(part.loaded.document.document_id)
    assert window.quick_access.identities == ("file.save", "edit.undo")
    assert window.action_catalog.get("file.save") in window.main_toolbar.actions()
    window.activate_session_document(sketch.loaded.document.document_id)
    assert window.quick_access.identities == ("file.open",)
    assert window.application_button in window.main_toolbar.findChildren(
        type(window.application_button)
    )
    window.act_reset_layout.trigger()
    assert window.quick_access.identities == window.quick_access.defaults
    window.activate_session_document(part.loaded.document.document_id)
    assert window.quick_access.identities == ("file.save", "edit.undo")


def test_main_window_configures_quick_access_only_after_confirm(qtbot: QtBot) -> None:
    from PySide6.QtCore import QTimer

    from mycad.app import build_app
    from mycad.ui.main_window import MainWindow
    from mycad.ui.quick_access import QuickAccessDialog

    window = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.show()
    before = window.quick_access.identities

    def remove_and_cancel() -> None:
        dialog = window.findChild(QuickAccessDialog)
        assert dialog is not None
        try:
            dialog.selected.setCurrentRow(0)
            dialog.remove_button.click()
        finally:
            dialog.reject()

    QTimer.singleShot(0, remove_and_cancel)
    window.act_customize_quick_access.trigger()
    assert window.quick_access.identities == before

    def remove_and_confirm() -> None:
        dialogs = window.findChildren(QuickAccessDialog)
        dialog = next(item for item in dialogs if item.isVisible())
        try:
            dialog.selected.setCurrentRow(0)
            dialog.remove_button.click()
        finally:
            dialog.accept()

    QTimer.singleShot(0, remove_and_confirm)
    window.act_customize_quick_access.trigger()
    assert window.quick_access.identities == before[1:]
    assert window.quick_access.store.load("part", ()) == before[1:]
    window.close()


def test_main_window_quick_access_restores_after_restart(qtbot: QtBot) -> None:
    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    first_services = build_app(discoverers=[])
    first = MainWindow(services=first_services)
    qtbot.addWidget(first)
    first.bind_document(new_document(first_services))
    first.quick_access.set_actions(("edit.undo", "plugin.removed", "file.save"))
    first.close()
    second_services = build_app(discoverers=[])
    second = MainWindow(services=second_services)
    qtbot.addWidget(second)
    second.bind_document(new_document(second_services))
    assert second.quick_access.identities == ("edit.undo", "plugin.removed", "file.save")
    actions = second.main_toolbar.actions()
    missing = next(action for action in actions if "plugin.removed" in action.toolTip())
    assert not missing.isEnabled()
    assert second.act_save in actions and second.act_undo in actions
    second.close()


def test_removed_plugin_action_during_worker_does_not_restore_deleted_qaction(qtbot: QtBot) -> None:
    from threading import Event

    from PySide6.QtGui import QAction

    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services))
    window.show()
    action = QAction("插件动作", window)
    window.action_catalog.register("plugin.temporary", action)
    window.quick_access.set_actions(("plugin.temporary",))
    unit = window.execution_unit
    assert unit is not None
    started, release = Event(), Event()

    def work() -> None:
        started.set()
        assert release.wait(20)

    try:
        assert unit.submit(
            work, operation="test-plugin-removal", session_id=window.drawing_workbench.session_id
        )
        qtbot.waitUntil(started.is_set, timeout=10000)
        window.action_catalog.unregister("plugin.temporary")
        action.deleteLater()
        qtbot.wait(50)
    finally:
        release.set()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=20000)
    missing = next(
        item for item in window.main_toolbar.actions() if "plugin.temporary" in item.toolTip()
    )
    assert not missing.isEnabled()
    window.close()


def test_shortcut_conflicts_report_enabled_shared_window_actions(qtbot: QtBot) -> None:
    from PySide6.QtGui import QAction, QKeySequence

    from mycad.app import build_app
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(window)
    action = QAction("自定义同键动作", window)
    action.setShortcut(QKeySequence("Ctrl+N"))
    window.addAction(action)
    conflicts = dict(window.shortcut_conflicts())
    assert "Ctrl+N" in conflicts
    assert "新建" in conflicts["Ctrl+N"] and "自定义同键动作" in conflicts["Ctrl+N"]
    action.setEnabled(False)
    assert "Ctrl+N" not in dict(window.shortcut_conflicts())
    assert window.act_new.shortcut() == QKeySequence("Ctrl+N")
    window.close()
