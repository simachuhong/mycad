# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared flange fixtures for the T10b plan/validate/history tests."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

FLANGE_VOLUME = math.pi * 8.0 * (40.0**2 - 10.0**2 - 4 * 3.0**2)

_TOP_FACE: dict[str, object] = {"surface": "plane", "axis": "+Z", "rank": 0}

FLANGE_PLAN: dict[str, object] = {
    "metadata": {
        "part_no": "FLANGE-DEMO-001",
        "revision": "A",
        "material": "Q235",
        "source": "example",
    },
    "steps": [
        {
            "id": "feature.cylinder",
            "version": 1,
            "params": {"radius": 40, "height": 8, "center": [0, 0, 0], "mode": "new"},
            "affected_object": "cylinder_body",
        },
        {
            "id": "feature.hole",
            "version": 1,
            "params": {
                "target_face": _TOP_FACE,
                "position": {"kind": "center"},
                "diameter": 20,
                "depth": {"kind": "through_all"},
            },
            "affected_object": "hole",
        },
        {
            "id": "feature.hole_pattern",
            "version": 1,
            "params": {
                "base_hole": {
                    "target_face": _TOP_FACE,
                    "position": {"kind": "center"},
                    "diameter": 6,
                    "depth": {"kind": "through_all"},
                },
                "pattern": {"kind": "polar", "radius": 25, "count": 4, "start_angle_deg": 0},
            },
            "affected_object": "hole_pattern",
        },
    ],
}


def flange_plan() -> dict[str, object]:
    """A fresh deep copy each call so tests can mutate freely."""
    return copy.deepcopy(FLANGE_PLAN)


def write_plan(path: Path, plan: object) -> Path:
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return path
