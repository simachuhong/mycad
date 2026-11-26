# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared frozen entry; spawn must be handled before loading CAD or Qt."""

import multiprocessing
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.argv[1:] == ["--legacy-layout"]:
        from mycad.ui.legacy_frame_export import main

        for stream in (sys.stdin, sys.stdout, sys.stderr):
            if stream is not None:
                reconfigure = cast(
                    "Callable[..., None] | None", getattr(stream, "reconfigure", None)
                )
                if reconfigure is not None:
                    reconfigure(encoding="utf-8")
    elif Path(sys.executable).stem.casefold() == "mycad-cli":
        from mycad.cli.__main__ import main
    else:
        from mycad.ui.desktop_launcher import main

    handle: int | None = None
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        create_mutex.restype = ctypes.c_void_p
        handle = cast("int | None", create_mutex(None, False, "MyCAD.Desktop.Running"))
        if handle is None:
            raise ctypes.WinError(ctypes.get_last_error())
    # Keep the handle alive until the process exits, including console workers.
    raise SystemExit(main())
