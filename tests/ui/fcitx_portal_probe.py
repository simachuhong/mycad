# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Isolated X11/Fcitx process used by the opt-in input method integration test."""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
import traceback
from typing import cast, override
from unittest.mock import patch

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QApplication

from mycad.ui.input_method import (
    fcitx_ibus_portal_available,
    native_fcitx_available,
    prepare_input_method,
)
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog


class PreeditObserver(QObject):
    """Observe real input method composition events without changing them."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.active = False

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.InputMethod and isinstance(event, QInputMethodEvent):
            self.active = bool(event.preeditString())
        return False


def main() -> int:
    fcitx = subprocess.Popen(
        ["fcitx5", "-D", "--disable", "cloudpinyin,wayland"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not fcitx_ibus_portal_available():
            if fcitx.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("isolated Fcitx portal did not become available")
            time.sleep(0.1)
        native = native_fcitx_available()
        if os.environ.get("MYCAD_TEST_FULL_STARTUP") == "1":
            return run_entry_probe(native)
        prepare_input_method()
        if not native and (
            os.environ.get("QT_IM_MODULE") != "ibus" or "IBUS_USE_PORTAL" not in os.environ
        ):
            raise RuntimeError("Fcitx compatibility fallback was not selected")
        return run_probe()
    finally:
        fcitx.terminate()
        try:
            fcitx.wait(timeout=5)
        except subprocess.TimeoutExpired:
            fcitx.kill()
            fcitx.wait(timeout=5)


def run_probe() -> int:
    app = QApplication([])
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    editor.resize(1200, 800)
    editor.show()
    editor.activateWindow()
    exercise_editor(app, editor)
    editor.close()
    return 0


def run_entry_probe(native: bool) -> int:
    from mycad.ui import entry

    class ProbeWindow(MainWindow):
        @override
        def show(self) -> None:
            super().show()
            QTimer.singleShot(0, self.exercise)

        def exercise(self) -> None:
            try:
                if not native and (
                    os.environ.get("QT_IM_MODULE") != "ibus" or "IBUS_USE_PORTAL" not in os.environ
                ):
                    raise RuntimeError("GUI entry did not configure the Fcitx portal")
                self.resize(1200, 800)
                self.act_new_drawing.trigger()
                self.workspace_tabs.activate("sketch")
                editor = self.active_sketch_dialog()
                app = QApplication.instance()
                if editor is None or not isinstance(app, QApplication):
                    raise RuntimeError("GUI entry did not open a drawing workspace")
                exercise_editor(app, editor)
            except Exception:
                traceback.print_exc()
                QApplication.exit(1)
            else:
                QApplication.exit(0)

    with patch.object(entry, "MainWindow", ProbeWindow):
        return entry.run_gui()


def exercise_editor(app: QApplication, editor: SketchEditorDialog) -> None:
    editor.window().activateWindow()
    bar = editor.drawing_command_bar
    preedit = PreeditObserver(bar.input)
    bar.input.installEventFilter(preedit)
    bar.input.setFocus()

    def pump(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

    pump(1.5)
    method = os.environ.get("MYCAD_TEST_IME_METHOD", "pinyin")
    subprocess.run(["fcitx5-remote", "-s", method], check=True)
    subprocess.run(["fcitx5-remote", "-o"], check=True)
    pump(0.5)
    x11 = ctypes.CDLL("libX11.so.6")
    xtest = ctypes.CDLL("libXtst.so.6")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.restype = ctypes.c_ubyte
    x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
    x11.XStringToKeysym.restype = ctypes.c_ulong
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    xtest.XTestFakeKeyEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_ulong,
    ]
    display = cast("int | None", x11.XOpenDisplay(None))
    if display is None:
        raise RuntimeError("isolated X11 display unavailable")
    x11.XSetInputFocus(display, int(editor.window().winId()), 1, 0)
    x11.XFlush(display)
    pump(0.2)

    def key(name: str) -> None:
        code = x11.XKeysymToKeycode(display, x11.XStringToKeysym(name.encode()))
        if not code:
            raise ValueError(f"X11 key unavailable: {name}")
        xtest.XTestFakeKeyEvent(display, code, 1, 0)
        xtest.XTestFakeKeyEvent(display, code, 0, 0)
        x11.XFlush(display)
        pump(0.3)

    editor.canvas.set_tool("选择元素")
    previous_tool = editor.canvas.tool
    key("n")
    key("i")
    assert preedit.active and bar.input.text() == ""
    key("space")
    committed = bar.input.text()
    assert any("\u4e00" <= character <= "\u9fff" for character in committed)
    if method == "pinyin":
        assert committed == "你"
    assert editor.canvas.tool == previous_tool
    bar.input.clear()
    editor.canvas.set_tool("直线")
    editor.canvas.add_coordinate_point((0, 0))
    bar.input.setFocus()
    pump(0.2)
    key("n")
    key("i")
    assert preedit.active and editor.canvas.has_pending_geometry
    key("Escape")
    assert not preedit.active and editor.canvas.has_pending_geometry
    key("Escape")
    assert not editor.canvas.has_pending_geometry
    editor.canvas.set_tool("直线")
    editor.canvas.add_coordinate_point((0, 0))
    bar.input.clear()
    bar.input.setFocus()
    pump(0.2)
    key("n")
    key("i")
    assert preedit.active and editor.canvas.has_pending_geometry
    key("Return")
    assert editor.canvas.has_pending_geometry and editor.canvas.tool == "直线"
    bar.input.clear()
    key("n")
    key("i")
    assert preedit.active
    editor.canvas.setFocus()
    pump(0.5)
    assert editor.canvas.has_pending_geometry and editor.canvas.tool == "直线"
    key("Escape")
    assert not editor.canvas.has_pending_geometry
    subprocess.run(["fcitx5-remote", "-c"], check=True)
    bar.input.clear()
    bar.input.setFocus()
    pump(0.2)
    for name in (
        "l",
        "i",
        "n",
        "e",
        "Return",
        "0",
        "comma",
        "0",
        "Return",
        "2",
        "comma",
        "0",
        "Return",
    ):
        key(name)
    assert len(editor.canvas.entities) == 1
    line = editor.canvas.entities[0]
    from mycad.core.sketch import LineEntity

    assert isinstance(line, LineEntity)
    assert line.start_mm == (0, 0) and line.end_mm == (2, 0)


if __name__ == "__main__":
    raise SystemExit(main())
