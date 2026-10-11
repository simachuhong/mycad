# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Emit GitHub Actions ``::error::`` annotations from a pytest JUnit XML.

CI writes ``test-results.xml`` so failing test nodeids surface through the
annotations API, which stays readable without log-download rights (the raw
log API needs admin access on the repo).

Deliberately property-free: a nodeid such as ``tests/test_x.py::test_y``
contains ``::`` which would terminate the workflow-command property block,
so the nodeid travels in the message body instead.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

MAX_MESSAGE_CHARS = 240


def failure_entries(root: ET.Element) -> list[tuple[str, str]]:
    """Collect ``(nodeid, first message line)`` for every failure/error."""
    entries: list[tuple[str, str]] = []
    for case in root.iter("testcase"):
        for kind in ("failure", "error"):
            outcome = case.find(kind)
            if outcome is None:
                continue
            classname = case.get("classname", "")
            name = case.get("name", "")
            nodeid = f"{classname}::{name}" if classname else name
            raw = (outcome.get("message") or outcome.text or kind).strip()
            first_line = raw.splitlines()[0] if raw else kind
            entries.append((nodeid, first_line[:MAX_MESSAGE_CHARS]))
    return entries


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <junit-xml>", file=sys.stderr)
        return 2
    try:
        root = ET.parse(argv[1]).getroot()
    except (ET.ParseError, OSError) as exc:
        # A missing/partial XML (e.g. cancelled run) must not fail the step.
        print(f"::warning::could not parse {argv[1]}: {exc}")
        return 0
    for nodeid, first_line in failure_entries(root):
        # Escape '%' so a literal '%0A'/%0D' in a message cannot inject breaks.
        safe = first_line.replace("%", "%25")
        print(f"::error::{nodeid}: {safe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
