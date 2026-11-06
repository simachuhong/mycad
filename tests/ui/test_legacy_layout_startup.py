# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Regression for a saved dock layout that crashed Qt while showing the window."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "linux" or not os.environ.get("DISPLAY"), reason="X11 required")
def test_saved_legacy_layout_opens_real_x11_window(tmp_path: Path) -> None:
    config = tmp_path / "MyCAD" / "MyCAD.conf"
    config.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parent / "fixtures" / "legacy_main_window_layout.conf", config)
    code = """
from PySide6.QtCore import QTimer
from mycad.ui.main_window import MainWindow
from mycad.ui.entry import run_gui
original = MainWindow.show
def show(window):
    original(window)
    QTimer.singleShot(500, window.close)
MainWindow.show = show
raise SystemExit(run_gui())
"""
    environment = os.environ.copy()
    environment["XDG_CONFIG_HOME"] = str(tmp_path)
    environment["QT_QPA_PLATFORM"] = "xcb"
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr
