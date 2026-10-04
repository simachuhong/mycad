# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Scripted acceptance for the six phase-0 ADRs (T4).

Pathlib + regex only, no third-party deps. Asserts:
- docs/adr/ holds exactly six files named ADR-001..006 with an ASCII slug.
- Every ADR carries the five MADR-lite section headers
  (Status / Context / Decision / Consequences / References).
- Per-ADR mandated keyword hits, located by filename prefix.
- The literal deviation heading appears exactly twice across all six files,
  once in ADR-001 and once in ADR-006 (located by filename, not content).
- No blocklisted premature-implementation phrase appears anywhere under
  docs/adr/ (exact phrases, so legitimate "not implemented in phase 0"
  wording is not false-positived).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = REPO_ROOT / "docs" / "adr"

# File name contract: ADR-00N-<slug>.md, N in 1..6, lowercase ASCII slug.
FILENAME_RE = re.compile(r"^ADR-(?P<number>00[1-6])-[a-z][a-z0-9-]*\.md$")

# MADR-lite section headers. Status is a fixed field line; the rest are
# level-2 headings that must each appear verbatim.
STATUS_RE = re.compile(r"^Status: Accepted 2026-09-17$", re.MULTILINE)
SECTION_HEADING_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Context", re.compile(r"^## Context$", re.MULTILINE)),
    ("Decision", re.compile(r"^## Decision$", re.MULTILINE)),
    ("Consequences", re.compile(r"^## Consequences$", re.MULTILINE)),
    ("References", re.compile(r"^## References$", re.MULTILINE)),
)

# The deviation marker heading. Exactly two occurrences are allowed across
# the whole ADR set, one in ADR-001 and one in ADR-006.
DEVIATION_HEADING_RE = re.compile(r"^## 基线偏离$", re.MULTILINE)

# Tokens that must appear in the ADR located by filename prefix.
REQUIRED_TOKENS: dict[str, tuple[str, ...]] = {
    "ADR-001": ("重放", "history_replay"),
    "ADR-002": ("timestamp_utc", "amendments", "named_groups"),
    "ADR-003": (
        "api_version",
        "CommandContribution",
        "EntryPoint.module",
        "missing-manifest",
        "incompatible-api",
    ),
    "ADR-004": ("confirm_execute", "plan_id", "A19"),
    "ADR-005": (
        "DE_Wrapper",
        "DUMB_SOLID",
        "ASSEMBLY_WITH_ATTRS",
        "EDITABLE_FEATURES",
        "DWG",
        "priority",
        "ProviderConflictError",
    ),
    "ADR-006": ("glibc", "2.31", "LoongArch", "manylinux_2_31"),
}

# Tokens that must NOT appear in the ADR located by filename prefix.
FORBIDDEN_TOKENS: dict[str, tuple[str, ...]] = {
    "ADR-002": ("imported_solid",),
}

# Exact premature-implementation phrases. A literal substring hit anywhere
# under docs/adr/ fails the suite. Deliberately an exact-phrase list (not
# fuzzy forbidden words) so legitimate negative phrasing survives.
BLOCKLIST_PHRASES: tuple[str, ...] = (
    "阶段 0 实现 MCP server",
    "阶段 0 实现 PySide6",
    "阶段 0 接入真实 LLM",
    "阶段 0 实现 DWG 写入",
)

DEVIATION_ALLOWED_PREFIXES = ("ADR-001-", "ADR-006-")


def _adr_files() -> list[Path]:
    """All files under docs/adr/, unfiltered; layout checks run on this."""
    if not ADR_DIR.is_dir():
        return []
    return sorted(path for path in ADR_DIR.iterdir() if path.is_file())


def _locate(prefix: str) -> Path:
    """The unique ADR file whose name starts with the given prefix."""
    matches = [path for path in _adr_files() if path.name.startswith(prefix + "-")]
    assert len(matches) == 1, f"expected exactly one {prefix}-*.md file, found {matches}"
    return matches[0]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_adr_dir_holds_exactly_six_numbered_files() -> None:
    files = _adr_files()
    assert files, "docs/adr/ does not exist or holds no files"
    numbers: list[str] = []
    for path in files:
        match = FILENAME_RE.match(path.name)
        assert match is not None, f"unexpected file name in docs/adr/: {path.name}"
        numbers.append(match.group("number"))
    assert len(files) == 6, f"expected exactly 6 ADR files, found {len(files)}"
    assert sorted(numbers) == ["001", "002", "003", "004", "005", "006"]


@pytest.mark.parametrize("prefix", sorted(REQUIRED_TOKENS))
def test_each_adr_has_the_five_section_headers(prefix: str) -> None:
    text = _read(_locate(prefix))
    assert STATUS_RE.search(text) is not None, f"{prefix}: missing Status field line"
    for name, pattern in SECTION_HEADING_RES:
        assert pattern.search(text) is not None, f"{prefix}: missing ## {name} heading"


@pytest.mark.parametrize("prefix", sorted(REQUIRED_TOKENS))
def test_per_adr_required_and_forbidden_tokens(prefix: str) -> None:
    path = _locate(prefix)
    text = _read(path)
    for token in REQUIRED_TOKENS[prefix]:
        assert token in text, f"{path.name}: required token missing: {token!r}"
    for token in FORBIDDEN_TOKENS.get(prefix, ()):
        assert token not in text, f"{path.name}: forbidden token present: {token!r}"


def test_deviation_heading_count_is_two_and_located_by_filename() -> None:
    total = 0
    for path in _adr_files():
        count = len(DEVIATION_HEADING_RE.findall(_read(path)))
        total += count
        if path.name.startswith(DEVIATION_ALLOWED_PREFIXES):
            assert count == 1, f"{path.name}: expected exactly one deviation heading"
        else:
            assert count == 0, f"{path.name}: deviation heading is not allowed here"
    assert total == 2, f"expected exactly 2 deviation headings in total, found {total}"


def test_no_blocklisted_premature_implementation_phrase() -> None:
    for path in _adr_files():
        text = _read(path)
        for phrase in BLOCKLIST_PHRASES:
            assert phrase not in text, f"{path.name}: blocklisted phrase present: {phrase!r}"
