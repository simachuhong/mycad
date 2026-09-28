# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Baseline doc SHA256 fixture test."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

EXPECTED_DOCS: tuple[str, ...] = (
    "docs/需求分析书.md",
    "docs/技术路线.md",
    "docs/UI设计初稿.md",
)


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_baseline_fixture_exists_and_has_three_keys() -> None:
    repo = Path(__file__).resolve().parent.parent
    fixture = repo / "tests" / "fixtures" / "baseline_doc_sha256.json"
    assert fixture.exists(), "baseline fixture missing — run scripts/gen_baseline_hashes.py"

    payload = json.loads(fixture.read_text(encoding="utf-8"))
    assert set(payload.keys()) == set(EXPECTED_DOCS), (
        f"baseline fixture keys drift: {sorted(payload.keys())} vs {sorted(EXPECTED_DOCS)}"
    )


def test_baseline_fixture_matches_current_doc_hashes() -> None:
    repo = Path(__file__).resolve().parent.parent
    fixture = repo / "tests" / "fixtures" / "baseline_doc_sha256.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))

    for rel_path in EXPECTED_DOCS:
        doc = repo / rel_path
        assert doc.exists(), f"baseline doc missing on disk: {rel_path}"
        current = _sha256_of(doc)
        stored = payload[rel_path]
        assert current == stored, (
            f"{rel_path} SHA256 drift: current={current} stored={stored}. "
            f"Re-run scripts/gen_baseline_hashes.py only when the doc update is intentional."
        )


def test_reverse_self_test_for_baseline(tmp_path: Path) -> None:
    """If a doc changes after the fixture is recorded, the test fails loudly."""

    payload = {
        "docs/需求分析书.md": "0" * 64,
        "docs/技术路线.md": "0" * 64,
        "docs/UI设计初稿.md": "0" * 64,
    }
    bad = tmp_path / "baseline_doc_sha256.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")

    parsed = json.loads(bad.read_text(encoding="utf-8"))
    assert parsed["docs/需求分析书.md"] == "0" * 64
