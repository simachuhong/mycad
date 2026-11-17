# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Select compatible Qt input method integration before creating QApplication."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import cast

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QPluginLoader


def native_fcitx_available() -> bool:
    """Check Qt's actual plugin paths and whether the Fcitx module can load."""
    for root in QCoreApplication.libraryPaths():
        directory = Path(root) / "platforminputcontexts"
        for path in directory.glob("*fcitx*.so"):
            loader = QPluginLoader(str(path))
            if loader.load():
                loader.unload()
                return True
    return False


def bundled_ibus_available() -> bool:
    """Check whether the matching Qt IBus input context can load."""
    bundled = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    plugin = bundled / "platforminputcontexts" / "libibusplatforminputcontextplugin.so"
    if not plugin.is_file():
        return False
    loader = QPluginLoader(str(plugin))
    if not loader.load():
        return False
    loader.unload()
    return True


def fcitx_ibus_portal_available() -> bool:
    """Require both D-Bus names to belong to the same Fcitx5 process."""
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusConnectionInterface

        interface = cast(
            "QDBusConnectionInterface | None", QDBusConnection.sessionBus().interface()
        )
        if interface is None:
            return False
        fcitx = interface.servicePid("org.fcitx.Fcitx5")
        portal = interface.servicePid("org.freedesktop.portal.IBus")
        return (
            fcitx.isValid()
            and portal.isValid()
            and fcitx.value() > 0
            and fcitx.value() == portal.value()
        )
    except (ImportError, RuntimeError):
        return False


def prefer_bundled_qt_plugins() -> None:
    """Put the matching Qt plugin directory ahead of external plugin paths."""
    bundled = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
    paths = QCoreApplication.libraryPaths()
    QCoreApplication.setLibraryPaths([bundled, *(path for path in paths if path != bundled)])


def prepare_input_method() -> None:
    """Use Qt's bundled IBus portal bridge if the configured Fcitx plugin is unusable."""
    if (
        sys.platform != "linux"
        or os.environ.get("QT_IM_MODULE", "").lower() not in ("fcitx", "fcitx5")
        or os.environ.get("QT_IM_MODULES")
        or native_fcitx_available()
        or not bundled_ibus_available()
        or not fcitx_ibus_portal_available()
    ):
        return
    prefer_bundled_qt_plugins()
    os.environ["QT_IM_MODULE"] = "ibus"
    os.environ.setdefault("IBUS_USE_PORTAL", "1")
