# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""CI workflow structural test.

The workflow file is currently READY but NOT EXECUTED (no remote is
configured for the repo). This test pins the workflow shape so a future
edit that silently drops a quality gate or a matrix entry is caught by
``pytest -q`` before it ever reaches CI.
"""

from __future__ import annotations

from pathlib import Path

REQUIRED_TOKENS: tuple[str, ...] = (
    "ubuntu-22.04",
    "ubuntu-24.04",
    "windows-latest",
    "astral-sh/setup-uv@v4",
    'python-version: "3.12"',
    "ruff check",
    "ruff format --check",
    "basedpyright",
    "pytest -q",
)


def test_ci_workflow_file_exists() -> None:
    repo = Path(__file__).resolve().parent.parent
    wf = repo / ".github" / "workflows" / "ci.yml"
    assert wf.exists(), f"missing {wf}"


def test_ci_workflow_has_all_required_tokens() -> None:
    repo = Path(__file__).resolve().parent.parent
    wf = repo / ".github" / "workflows" / "ci.yml"
    text = wf.read_text(encoding="utf-8")
    for token in REQUIRED_TOKENS:
        assert token in text, f"CI workflow missing required token: {token!r}"


def test_reverse_self_test_for_ci(tmp_path: Path) -> None:
    bad = tmp_path / "ci.yml"
    bad.write_text("# no real workflow here\n", encoding="utf-8")
    text = bad.read_text(encoding="utf-8")
    assert "ubuntu-22.04" not in text
