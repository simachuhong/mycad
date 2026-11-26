# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Desktop startup with persistent diagnostics when no console is attached."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from logging.handlers import RotatingFileHandler
from pathlib import Path


def show_error(message: str) -> None:
    """Keep a startup error visible even when the console is absent."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    application = QApplication.instance() or QApplication([])
    QMessageBox.critical(None, "MyCAD 启动失败", message)
    # Hold a reference until the modal dialog has closed.
    application.processEvents()


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MyCAD" / "logs" / str(os.getpid())
    )
    root.mkdir(parents=True, exist_ok=True)
    path = root / "application.log"
    handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger("mycad.desktop")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        if len(args) > 1 or (args and args[0].startswith("-")):
            show_error(f"请只指定一个 MyCAD 文档。\n日志：{path}")
            return 2
        logger.info("Starting MyCAD; document=%s", args[0] if args else "<start page>")
        with ExitStack() as stack:
            # PyInstaller's windowed bootloader sets these streams to None.
            if sys.stdout is None or sys.stderr is None:
                output = stack.enter_context((root / "stdio.log").open("a", encoding="utf-8"))
                if sys.stdout is None:
                    stack.enter_context(redirect_stdout(output))
                if sys.stderr is None:
                    stack.enter_context(redirect_stderr(output))
            from mycad.ui.entry import run_gui

            result = run_gui(Path(args[0]) if args else None)
        logger.info("MyCAD exited: %s", result)
        return result
    except Exception:
        logger.exception("Desktop startup failed")
        show_error(f"MyCAD 启动失败，请将此日志提供给开发者：\n{path}")
        return 1
    finally:
        logger.removeHandler(handler)
        handler.close()
