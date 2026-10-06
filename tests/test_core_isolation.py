# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Core isolation: ``mycad.core`` must not pull build123d / OCP (#round7-NB6).

The assertion runs in a FRESH subprocess — never in the main pytest
process, whose module state is polluted by the geom suite — with
PYTHONPATH pointing at the repo root. The reverse self-proof (importing
``mycad.geom`` MUST bring both backends in) guards against a
vacuously-passing forward assertion.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHILD_CODE = "\n".join(
    [
        "import sys",
        "import mycad.core",
        "assert 'build123d' not in sys.modules, 'mycad.core leaked build123d'",
        "assert 'OCP' not in sys.modules, 'mycad.core leaked OCP'",
        "import mycad.geom",
        "assert 'build123d' in sys.modules, 'reverse self-proof failed: no build123d'",
        "assert 'OCP' in sys.modules, 'reverse self-proof failed: no OCP'",
    ]
)


def test_core_import_is_clean_and_geom_proof_is_alive() -> None:
    result = subprocess.run(
        [sys.executable, "-c", CHILD_CODE],
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"isolation child failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
