# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Run the installed CLI plan/export path without desktop packages."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DESKTOP_MODULES = ("PySide6", "pyqtgraph", "OpenGL", "shiboken6")


def _run_cli(executable: str, *args: str) -> bool:
    result = subprocess.run(
        (executable, *args),
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode == 0:
        return True
    sys.stderr.write(result.stdout)
    sys.stderr.write(result.stderr)
    return False


def _check_gui_install_hint(executable: str) -> bool:
    result = subprocess.run(
        (executable, "gui"),
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    expected_hint = "uv sync --extra desktop"
    if result.returncode == 1 and expected_hint in result.stderr:
        return True
    print("headless `mycad gui` did not provide the desktop install hint", file=sys.stderr)
    sys.stderr.write(result.stdout)
    sys.stderr.write(result.stderr)
    return False


def main() -> int:
    """Validate and execute the flange plan in a temporary output folder."""
    present = [name for name in DESKTOP_MODULES if importlib.util.find_spec(name) is not None]
    if present:
        print(f"headless environment unexpectedly has desktop modules: {present}", file=sys.stderr)
        return 1

    executable = shutil.which("mycad")
    if executable is None:
        print("installed `mycad` entry point was not found on PATH", file=sys.stderr)
        return 1
    if not _check_gui_install_hint(executable):
        return 1

    with tempfile.TemporaryDirectory(prefix="mycad-headless-") as temp_dir:
        plan = Path(temp_dir) / "flange_plan.json"
        shutil.copyfile(REPO / "examples" / "flange_plan.json", plan)
        plan_arg = plan.as_posix()
        if not _run_cli(executable, "validate", plan_arg):
            return 1
        if not _run_cli(executable, "run", "--json", plan_arg):
            return 1
        outputs = (
            plan.with_suffix(".step"),
            plan.with_suffix(".stl"),
            plan.with_suffix(".mc.json"),
        )
        missing = [path.name for path in outputs if not path.is_file() or path.stat().st_size == 0]
        if missing:
            print(f"headless CLI did not produce non-empty outputs: {missing}", file=sys.stderr)
            return 1
        print("headless CLI produced STEP, STL, and .mc.json outputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
