# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Windows entry failures stay observable without a console."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mycad.ui import desktop_launcher, entry


def _ignore_message(_message: str) -> None:
    pass


def test_startup_failure_records_traceback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    def broken(_path: Path | None = None) -> int:
        raise RuntimeError("启动失败 probe")

    monkeypatch.setattr(entry, "run_gui", broken)
    monkeypatch.setattr(desktop_launcher, "show_error", _ignore_message)
    assert desktop_launcher.main([]) == 1
    log = tmp_path / "MyCAD" / "logs" / str(os.getpid()) / "application.log"
    assert "RuntimeError: 启动失败 probe" in log.read_text(encoding="utf-8")


def test_invalid_arguments_fail_without_opening_gui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(desktop_launcher, "show_error", _ignore_message)
    assert desktop_launcher.main(["a.my2d", "b.my2d"]) == 2


def test_windowed_streams_write_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    def run(_path: Path | None = None) -> int:
        print("窗口输出 probe")
        print("窗口错误 probe", file=sys.stderr)
        return 0

    monkeypatch.setattr(entry, "run_gui", run)
    with monkeypatch.context() as context:
        context.setattr(sys, "stdout", None)
        context.setattr(sys, "stderr", None)
        result = desktop_launcher.main([])
    assert result == 0
    log = (tmp_path / "MyCAD/logs" / str(os.getpid()) / "stdio.log").read_text(encoding="utf-8")
    assert "窗口输出 probe" in log
    assert "窗口错误 probe" in log


def test_layout_launcher_accepts_real_utf8_json() -> None:
    from mycad.core.drawing_text import TextStyleTable

    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    request: dict[str, object] = {
        "frames": [],
        "datums": [],
        "styles": TextStyleTable().to_mapping(),
        "application_name": "MyCAD 中文测试",
    }
    launcher = Path(__file__).resolve().parents[2] / "scripts/windows/launcher.py"
    result = subprocess.run(
        [sys.executable, str(launcher), "--legacy-layout"],
        input=json.dumps(request, ensure_ascii=False),
        capture_output=True,
        encoding="utf-8",
        env=environment,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "anchors": {},
        "skipped": {},
        "bounds": {},
        "datum_boxes": {},
        "notices": [],
    }
