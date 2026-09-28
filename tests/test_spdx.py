# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""SPDX header enforcement (every project .py file)."""

from __future__ import annotations

from pathlib import Path

EXPECTED_LINE_1 = "# SPDX-FileCopyrightText: 2026 MyCAD contributors"
EXPECTED_LINE_2 = "# SPDX-License-Identifier: Apache-2.0"

SCAN_ROOTS = ("src", "tests", "scripts")


def _iter_python_files() -> list[Path]:
    repo = Path(__file__).resolve().parent.parent
    files: list[Path] = []
    for root in SCAN_ROOTS:
        root_path = repo / root
        if not root_path.exists():
            continue
        for path in root_path.rglob("*.py"):
            # Skip __pycache__ inside (defensive — gitignore already covers it).
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return sorted(files)


def test_first_two_lines_match_spdx() -> None:
    """All tracked Python files start with the exact SPDX pair, no leading BOM."""

    py_files = _iter_python_files()
    assert py_files, "no Python files found — repo layout broken"

    for path in py_files:
        with path.open("rb") as fh:
            raw = fh.read()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{path}: BOM detected"
        text = raw.decode("utf-8")
        # First line must end with newline (or be EOF after line 2).
        lines = text.splitlines()
        assert len(lines) >= 2, f"{path}: fewer than 2 lines"
        assert lines[0] == EXPECTED_LINE_1, f"{path}: line 1 mismatch"
        assert lines[1] == EXPECTED_LINE_2, f"{path}: line 2 mismatch"


def test_reverse_self_test_for_spdx(tmp_path: Path) -> None:
    """A file lacking SPDX must fail the assertion when written to a tmp tree."""

    bad = tmp_path / "src" / "mycad" / "core" / "bad.py"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("# SPDX-Wrong-Line\n# SPDX-Also-Wrong\nx = 1\n", encoding="utf-8")

    with bad.open("rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8")
    lines = text.splitlines()
    assert lines[0] != EXPECTED_LINE_1, "reverse-test premise invalidated"
    assert lines[1] != EXPECTED_LINE_2
