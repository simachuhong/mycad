# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""sys.path injection for the in-process plugin fixtures (T9a).

The fixture trees under ``tests/fixtures/plugins`` are pure in-process
source fixtures (#round10-NB3): never installed, never packaged, never
touched by pip — only placed on ``sys.path`` for the duration of a
test that requests the fixture.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

#: tests/plugins/conftest.py -> parents[1] is ``tests/``; each fixture
#: tree directory under tests/fixtures/plugins is then importable as a
#: top-level package once this root lands on sys.path.
FIXTURE_ROOT: Path = Path(__file__).resolve().parents[1] / "fixtures" / "plugins"


@pytest.fixture
def plugin_fixture_path() -> Iterator[None]:
    """Put FIXTURE_ROOT on sys.path for one test, remove it afterwards.

    Idempotent: repeated or nested requests never duplicate the entry,
    and the cleanup removes the single inserted occurrence only.
    """
    entry = str(FIXTURE_ROOT)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    try:
        yield
    finally:
        if entry in sys.path:
            sys.path.remove(entry)
