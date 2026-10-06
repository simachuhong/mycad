# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Test-only STEP readback helper (T8b).

This is the ONE file in the whole tests tree allowed to import a
build123d *read* API (layering whitelist in tests/test_layering.py).
Product code has no STEP import path in Phase 0 (F-DOC-03 is stage 1,
ADR-005); this exists solely for export->readback roundtrip asserts.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import build123d
from build123d import Compound

# import_step's stub signature is partially unknown under basedpyright
# strict; the cast narrows it to the exact call shape used here. This is
# a cast, not a suppression comment (same pattern as mycad/geom/io.py).
_read_step = cast(Callable[[Path], Compound], build123d.import_step)


def read_step(path: Path) -> tuple[int, float]:
    """Read ``path`` back; return ``(solid count, volume in mm^3)``."""

    compound = _read_step(path)
    solids = compound.solids()
    return len(solids), sum(solid.volume for solid in solids)
