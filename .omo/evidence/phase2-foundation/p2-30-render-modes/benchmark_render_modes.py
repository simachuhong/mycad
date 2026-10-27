# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Compare BREP display extraction and scene refresh with the P2-09 baseline."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from mycad.benchmarks import summarize_samples

OUTPUT = Path(__file__).resolve().parent
BASELINE_PATH = Path(__file__).resolve().parents[2] / "p2-09-reference-benchmarks.json"
SIZES = (10, 50, 100)
SAMPLE_COUNT = 30
BOX_PARAMS = {"size_x": 180.0, "size_y": 120.0, "size_z": 10.0, "mode": "new"}


def _hole_params(index: int, count: int) -> dict[str, object]:
    columns = 11
    rows = (count + columns - 1) // columns
    row_pitch = 10.0 if count == 100 else 20.0
    return {
        "radius": 2.0,
        "height": 20.0,
        "center": [
            -75.0 + (index % columns) * 15.0,
            -((rows - 1) * row_pitch) / 2.0 + (index // columns) * row_pitch,
            0.0,
        ],
        "mode": "cut",
    }


def _elapsed_ms(callable_object: Callable[[], object]) -> float:
    start = time.perf_counter()
    callable_object()
    return (time.perf_counter() - start) * 1000.0


def _worker(size: int) -> dict[str, object]:
    from PySide6.QtWidgets import QApplication

    from mycad.app import build_app, new_document
    from mycad.ui.viewport import GLViewport

    app = QApplication.instance() or QApplication([])
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", BOX_PARAMS, "p2-30-benchmark")
    for index in range(size):
        loaded.bus.execute("feature.cylinder", _hole_params(index, size), "p2-30-benchmark")

    cold_default_ms = _elapsed_ms(services.kernel.viewport_data)
    hot_default = [_elapsed_ms(services.kernel.viewport_data) for _ in range(SAMPLE_COUNT)]
    viewport = GLViewport(viewport_port=services.kernel)
    viewport.bind_document(loaded)
    app.processEvents()
    refresh = [_elapsed_ms(viewport.refresh) for _ in range(SAMPLE_COUNT)]
    result = {
        "features": size,
        "boundary_edge_count": len(services.kernel.viewport_data()[0].boundary_edges),
        "mesh_triangle_count": len(services.kernel.viewport_data()[0].mesh.triangle_indices),
        "current_mesh_cold_default_ms": cold_default_ms,
        "current_mesh_hot_default_ms": summarize_samples(hot_default),
        "viewport_scene_refresh_ms": summarize_samples(refresh),
        "viewport_scene_refresh_samples_ms": refresh,
    }
    viewport.dispose()
    viewport.close()
    return result


def main() -> None:
    if len(sys.argv) == 2:
        size = int(sys.argv[1])
        print(json.dumps(_worker(size), default=lambda value: value.__dict__))
        return

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    baseline_by_size = {entry["features"]: entry for entry in baseline["results"]}
    results: list[dict[str, object]] = []
    for size in SIZES:
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        worker = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(size)],
            env=environment,
            check=True,
            capture_output=True,
            encoding="utf-8",
        )
        result = json.loads(worker.stdout)
        baseline_metric = baseline_by_size[size]["metrics"]["viewport_scene_refresh_offscreen"]
        baseline_p95 = baseline_metric["summary"]["p95_ms"]
        budget_ms = int((baseline_p95 * 1.25 + 4.999999) // 5) * 5
        result["p2_09_baseline_scene_refresh_p95_ms"] = baseline_p95
        result["p2_09_scene_refresh_budget_ms"] = budget_ms
        result["within_p2_09_scene_refresh_budget"] = (
            result["viewport_scene_refresh_ms"]["p95_ms"] <= budget_ms
        )
        results.append(result)

    report = {
        "benchmark": "P2-30 BREP boundaries and render modes",
        "sample_count": SAMPLE_COUNT,
        "comparison": "same workload and offscreen GL scene refresh scope as P2-09",
        "baseline": str(BASELINE_PATH.relative_to(Path.cwd())),
        "results": results,
    }
    (OUTPUT / "benchmark.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
