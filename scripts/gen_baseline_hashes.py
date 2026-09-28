# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Generate ``tests/fixtures/baseline_doc_sha256.json``.

Records the SHA256 of the three baseline docs so downstream evidence can
prove they have not drifted between commits. Run only when a baseline
doc is intentionally updated — every drift means a change to the public
contract (requirement / technical route / UI direction).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "tests" / "fixtures" / "baseline_doc_sha256.json"
DOCS: tuple[str, ...] = (
    "docs/需求分析书.md",
    "docs/技术路线.md",
    "docs/UI设计初稿.md",
)


def main(argv: list[str]) -> int:
    if argv and argv[0] in {"-h", "--help"}:
        print(f"usage: {Path(argv[0]).name} [check]", file=sys.stderr)
        return 0

    payload: dict[str, str] = {}
    for rel in DOCS:
        doc = REPO / rel
        if not doc.exists():
            print(f"error: missing baseline doc: {rel}", file=sys.stderr)
            return 2
        payload[rel] = hashlib.sha256(doc.read_bytes()).hexdigest()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT.relative_to(REPO)} with {len(payload)} keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
