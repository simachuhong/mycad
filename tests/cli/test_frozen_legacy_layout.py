# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Frozen layout requests use a console helper rather than the GUI executable."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from mycad.cli.legacy_dxf import legacy_layout_snapshot
from mycad.core.drawing_text import TextStyleTable


def test_frozen_layout_uses_sibling_console_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "中文 App" / "MyCAD.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    observed: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed.append(command)
        request = json.loads(kwargs["input"])
        assert request["frames"] == []
        return subprocess.CompletedProcess(
            command, 0, '{"anchors":{},"skipped":{},"bounds":{},"notices":[]}', ""
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert legacy_layout_snapshot((), TextStyleTable()) == ({}, {}, {}, (), {})
    assert observed == [[str(executable.with_name("MyCAD-cli.exe")), "--legacy-layout"]]
