# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Build evidence is derived from real output files, not a success placeholder."""

import hashlib
import json
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

_module = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts/windows/build_support.py")
)
finalize = cast("Callable[[Path], None]", _module["finalize"])
read_version = cast("Callable[[Path, int], str]", _module["read_version"])


def test_finalize_hashes_setup_and_records_source(tmp_path: Path) -> None:
    installer = tmp_path / "MyCAD-0.1.0.1-x64-Setup.exe"
    installer.write_bytes(b"installer artifact")
    (tmp_path / "build-info.json").write_text('{"commit":"abc123"}', encoding="utf-8")
    finalize(tmp_path)
    digest = hashlib.sha256(b"installer artifact").hexdigest()
    assert (tmp_path / "SHA256SUMS").read_text(encoding="utf-8") == (
        f"{digest}  MyCAD-0.1.0.1-x64-Setup.exe\n"
    )
    info = json.loads((tmp_path / "build-info.json").read_text(encoding="utf-8"))
    assert info["commit"] == "abc123"
    assert info["installers"][0]["sha256"] == digest


def test_finalize_rejects_missing_installer(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        finalize(tmp_path)
    assert not (tmp_path / "SHA256SUMS").exists()


def test_version_rejects_windows_overflow(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="0.1.0"', encoding="utf-8")
    assert read_version(tmp_path, 2) == "0.1.0.2"
    with pytest.raises(ValueError):
        read_version(tmp_path, 65536)
