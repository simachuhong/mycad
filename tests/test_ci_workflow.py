# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""CI workflow structural test.

The workflow runs on GitHub Actions (3-OS matrix, both push and PR). This
test pins the workflow shape so a future edit that silently drops a quality
gate, a matrix entry, or the failure-reporting step is caught by
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
    # GL offscreen stack: phase 1 pulls PySide6/PyOpenGL, whose offscreen
    # import path needs EGL/GL libraries the Linux runners do not ship.
    "Install GL offscreen libraries",
    "libxkbcommon-x11-0",
    "ruff check",
    "ruff format --check",
    "basedpyright",
    "pytest -q",
    "--junitxml",
    "report_junit_failures",
    "if: always()",
)


def test_ci_workflow_file_exists() -> None:
    repo = Path(__file__).resolve().parent.parent
    wf = repo / ".github" / "workflows" / "ci.yml"
    assert wf.exists(), f"missing {wf}"


def missing_tokens(text: str) -> list[str]:
    """Required tokens absent from a workflow rendering."""
    return [token for token in REQUIRED_TOKENS if token not in text]


def test_ci_workflow_has_all_required_tokens() -> None:
    repo = Path(__file__).resolve().parent.parent
    wf = repo / ".github" / "workflows" / "ci.yml"
    assert missing_tokens(wf.read_text(encoding="utf-8")) == []


def test_reverse_self_test_for_ci() -> None:
    """Feed the real detector a workflow with one gate dropped.

    Asserting a token is absent from a stub file proves nothing about
    ``missing_tokens``; this drives the same function the forward test
    uses.
    """
    repo = Path(__file__).resolve().parent.parent
    text = (repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert missing_tokens(text.replace("windows-latest", "ubuntu-latest")) == ["windows-latest"]
    assert missing_tokens(text.replace("basedpyright", "echo skip")) == ["basedpyright"]
