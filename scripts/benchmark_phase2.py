# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Collect repeatable Phase 2 geometry, viewport and interaction timings.

Run from the repository root with ``uv run python scripts/benchmark_phase2.py``.
Each feature count runs in a fresh subprocess so peak RSS is isolated by size.
The default run uses 30 repetitions for operations where repetition is cheap;
modeling reports every individual cut-command duration from its one history.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from mycad.app import build_app, new_document, open_app_document
from mycad.benchmarks import SampleSummary, summarize_samples
from mycad.core.persistence import save_document
from mycad.ui.viewport import GLViewport

try:
    import resource
except ImportError:  # pragma: no cover - reference machine is Linux
    resource = None


DEFAULT_SIZES = (10, 25, 50, 100)
DEFAULT_SAMPLES = 30
OUTPUT_PATH = Path(".omo/evidence/p2-09-reference-benchmarks.json")
BOX_PARAMS: dict[str, object] = {
    "size_x": 180.0,
    "size_y": 120.0,
    "size_z": 10.0,
    "mode": "new",
}
RAY_ORIGIN = (7.0, 7.0, 100.0)
RAY_DIRECTION = (0.0, 0.0, -1.0)


def _elapsed_ms(call: Callable[[], object]) -> float:
    start = time.perf_counter()
    call()
    return (time.perf_counter() - start) * 1000.0


def _cpu_model() -> str:
    """Read the Linux reference CPU name, with the portable fallback."""
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                return line.split(":", maxsplit=1)[1].strip()
    return platform.processor() or "unknown"


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def _runtime_metadata() -> dict[str, object]:
    return {
        "cpu": _cpu_model(),
        "logical_cpu_count": os.cpu_count(),
        "system": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "build123d": _package_version("build123d"),
        "cadquery_ocp_novtk": _package_version("cadquery-ocp-novtk"),
        "pyside6": _package_version("PySide6"),
        "pyqtgraph": _package_version("pyqtgraph"),
        "qt_platform": os.environ.get("QT_QPA_PLATFORM", "auto"),
    }


def _peak_rss_mb() -> float | None:
    """Return process high-water RSS in MiB, including native OCCT memory."""
    if resource is None:
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB; macOS reports bytes.
    return usage / (1024.0 if sys.platform.startswith("linux") else 1024.0**2)


def _hole_params(index: int, count: int) -> dict[str, object]:
    columns = 11
    rows = (count + columns - 1) // columns
    # The 100-feature extension uses a 10 mm row pitch to fit the legacy
    # 180 x 120 mm plate. 10/25/50 preserve the P2-00 15 x 20 mm grid.
    row_pitch = 10.0 if count == 100 else 20.0
    column = index % columns
    row = index // columns
    x = -75.0 + column * 15.0
    y = -((rows - 1) * row_pitch) / 2.0 + row * row_pitch
    return {
        "radius": 2.0,
        "height": 20.0,
        "center": [x, y, 0.0],
        "mode": "cut",
    }


def _metric(samples: list[float]) -> dict[str, object]:
    summary: SampleSummary = summarize_samples(samples)
    return {"summary": summary, "samples_ms": samples}


def _collect_size(size: int, sample_count: int) -> dict[str, object]:
    """Run one size in an isolated process and return raw plus summarized data."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    services = build_app(discoverers=[])
    loaded = new_document(services)
    modeling_samples: list[float] = []
    modeling_started = time.perf_counter()
    loaded.bus.execute("feature.box", BOX_PARAMS, confirmed_by="benchmark")
    for index in range(size):
        params = _hole_params(index, size)
        modeling_samples.append(
            _elapsed_ms(
                lambda params=params: loaded.bus.execute(
                    "feature.cylinder", params, confirmed_by="benchmark"
                )
            )
        )
    modeling_total_ms = (time.perf_counter() - modeling_started) * 1000.0

    metric_samples: dict[str, list[float]] = {
        "open_app_document": [],
        "undo_one": [],
        "redo_one": [],
        "current_mesh_cold_default": [],
        "current_mesh_hot_default": [],
        "current_mesh_cold_fine": [],
        "history_mesh_cold_default": [],
        "history_mesh_hot_default": [],
        "viewport_scene_refresh_offscreen": [],
        "ray_pick": [],
    }

    with tempfile.TemporaryDirectory(prefix="mycad-phase2-bench-") as temp_dir:
        archive = Path(temp_dir) / f"{size}-features.mc.json"
        save_document(loaded.document, archive)
        for _sample in range(sample_count):
            open_started = time.perf_counter()
            loaded = open_app_document(services, archive)
            metric_samples["open_app_document"].append(
                (time.perf_counter() - open_started) * 1000.0
            )
            metric_samples["undo_one"].append(_elapsed_ms(loaded.bus.undo))
            metric_samples["redo_one"].append(_elapsed_ms(loaded.bus.redo))

        metric_samples["current_mesh_cold_default"].append(
            _elapsed_ms(services.kernel.viewport_data)
        )
        metric_samples["current_mesh_hot_default"] = [
            _elapsed_ms(services.kernel.viewport_data) for _ in range(sample_count)
        ]
        metric_samples["current_mesh_cold_fine"].append(
            _elapsed_ms(lambda: services.kernel.viewport_data(0.05, 7.5))
        )
        state_ids = services.kernel.viewport_state_ids()
        history_state_index = max(0, len(state_ids) // 2 - 1)
        history_state = state_ids[history_state_index]
        metric_samples["history_mesh_cold_default"].append(
            _elapsed_ms(lambda: services.kernel.historical_viewport_data(history_state))
        )
        metric_samples["history_mesh_hot_default"] = [
            _elapsed_ms(lambda: services.kernel.historical_viewport_data(history_state))
            for _ in range(sample_count)
        ]

        viewport = GLViewport(viewport_port=services.kernel)
        viewport.bind_document(loaded)
        app.processEvents()
        metric_samples["viewport_scene_refresh_offscreen"] = [
            _elapsed_ms(viewport.refresh) for _ in range(sample_count)
        ]
        metric_samples["ray_pick"] = [
            _elapsed_ms(lambda: viewport.pick_current_entity_at_ray(RAY_ORIGIN, RAY_DIRECTION))
            for _ in range(sample_count)
        ]
        viewport.dispose()
        viewport.close()

    summaries = {name: _metric(values) for name, values in metric_samples.items()}
    summaries["modeling_cut_command"] = _metric(modeling_samples)
    return {
        "features": size,
        "commands": size + 1,
        "modeling_total_ms_one_history": modeling_total_ms,
        "metrics": summaries,
        "peak_rss_mb": _peak_rss_mb(),
        "memory_scope": "process high-water RSS, isolated subprocess, includes Python/Qt/OCP native allocations",
        "gui_refresh_scope": "offscreen scene graph refresh; excludes visible-window paint and GPU frame time",
        "workload": {
            "plate_mm": [180.0, 120.0, 10.0],
            "hole_radius_mm": 2.0,
            "cutter_height_mm": 20.0,
            "grid_columns": 11,
            "grid_pitch_mm": [15.0, 10.0 if size == 100 else 20.0],
            "history_mesh_sample": {
                "selection": "state_ids[max(0, len(state_ids) // 2 - 1)]",
                "index": history_state_index,
                "state_id": history_state,
            },
        },
        "runtime": _runtime_metadata(),
    }


def _worker(size: int, sample_count: int) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    print(json.dumps(_collect_size(size, sample_count), ensure_ascii=False))
    return 0


def _run_all(sizes: tuple[int, ...], sample_count: int, output: Path) -> int:
    worker_script = Path(__file__).resolve()
    results: list[dict[str, object]] = []
    for size in sizes:
        print(
            f"Benchmarking {size} features ({sample_count} operation samples)...", file=sys.stderr
        )
        worker = subprocess.run(
            [
                sys.executable,
                str(worker_script),
                "--worker-size",
                str(size),
                "--samples",
                str(sample_count),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        )
        results.append(json.loads(worker.stdout))

    report = {
        "benchmark": "MyCAD Phase 2 end-to-end baseline",
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sampling": {
            "repeat_count": sample_count,
            "percentile_method": "nearest-rank: sorted[ceil(p * n) - 1]",
            "small_sample_rule": "P95 is tagged small_sample below 30 observations",
        },
        "reference": _runtime_metadata(),
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=list(DEFAULT_SIZES))
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--worker-size", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if args.worker_size is not None:
        if args.worker_size < 1:
            parser.error("--worker-size must be positive")
        return _worker(args.worker_size, args.samples)
    if any(size < 1 for size in args.sizes):
        parser.error("all --sizes values must be positive")
    return _run_all(tuple(args.sizes), args.samples, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
