# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Always recapture every combination; no stale evidence reuse."""

import json
import os
import subprocess
import sys
from pathlib import Path

folder = Path(__file__).resolve().parent
reports = []
for scale in (1, 1.25, 1.5, 2):
    for size in ("1920x1080", "1366x768"):
        env = os.environ | {
            "QT_QPA_PLATFORM": "xcb",
            "QT_SCALE_FACTOR": str(scale),
            "MYCAD_CAPTURE_SIZE": size,
        }
        result = subprocess.run(
            [sys.executable, str(folder / "capture_workbench.py")],
            env=env,
            capture_output=True,
            encoding="utf-8",
        )
        (folder / f"capture-{size}-{scale}.log").write_text(
            result.stdout + result.stderr, encoding="utf-8"
        )
        if result.returncode:
            raise RuntimeError(f"{size}@{scale}: {result.stderr}")
        report = json.loads((folder / f"{size}-{scale:g}" / "report.json").read_text())
        reports.append(report)
        print(
            f"PASS {size} @ {scale}: DPR {report['dpr']}, 8 command layouts, preview/reselection/cancel",
            flush=True,
        )
(folder / "matrix.json").write_text(
    json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
