# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Run the desktop capture once per resolution and Qt scale factor."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent
CAPTURE_SCRIPT = OUTPUT / "capture_workbench.py"
SCALES = (1.0, 1.25, 1.5, 2.0)
RESOLUTIONS = ("1920x1080", "1366x768")


def main() -> None:
    matrix: list[dict[str, object]] = []
    for scale in SCALES:
        for resolution in RESOLUTIONS:
            report_path = OUTPUT / f"render-check-scale-{scale:g}-{resolution}.json"
            if report_path.exists():
                report = json.loads(report_path.read_text(encoding="utf-8"))
            else:
                environment = os.environ.copy()
                environment.update(
                    {
                        "QT_QPA_PLATFORM": "xcb",
                        "QT_SCALE_FACTOR": str(scale),
                        "MYCAD_CAPTURE_RESOLUTION": resolution,
                    }
                )
                result = subprocess.run(
                    [sys.executable, str(CAPTURE_SCRIPT)],
                    env=environment,
                    check=False,
                    capture_output=True,
                    encoding="utf-8",
                )
                if result.returncode != 0:
                    raise SystemExit(
                        f"capture failed for {scale:g} × {resolution}:\n"
                        f"{result.stderr}\n{result.stdout}"
                    )
                report = json.loads(result.stdout)
            captures = report["captures"]
            matrix.append(
                {
                    "scale_factor": scale,
                    "physical_target": resolution,
                    "qt_platform": report["qt_platform"],
                    "capture_count": len(captures),
                    "states": [capture["state"] for capture in captures],
                    "image_sizes": [capture["captured_image_size"] for capture in captures],
                    "viewport_shares": [
                        capture["viewport_share_of_window"] for capture in captures
                    ],
                    "bottom_panel_visibility": [
                        capture["bottom_panel_visible"] for capture in captures
                    ],
                }
            )
    output = {"tested_combinations": matrix}
    (OUTPUT / "render-check-matrix.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
