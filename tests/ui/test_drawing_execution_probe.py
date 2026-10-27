# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""T0 compare thread and process HLR through the real GUI executor.

The thread measurement is diagnostic: its failed 250 ms gate is preserved in
probe-thread.log. Only the replacement process path is a release candidate.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import platform
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import cast

import build123d
import pytest
from build123d import Compound, Cylinder, Pos
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from mycad.ui.execution import ExecutionResult, SerializedExecutionUnit
from tests.geom.test_drawing_projection_probe import benchmark_brep


@pytest.mark.parametrize("use_process", [False, True], ids=["thread-diagnostic", "process-gate"])
@pytest.mark.parametrize("columns", [10, 30], ids=["300-edges", "900-edges"])
def test_exact_hlr_execution_probe(
    qtbot: QtBot, tmp_path: Path, use_process: bool, columns: int
) -> None:
    shape = Compound(
        children=[Pos(x * 5, y * 5, 0) * Cylinder(2, 8) for x in range(columns) for y in range(10)]
    )
    archive = tmp_path / "source.brep"
    write_brep = cast("Callable[[Compound, Path], bool]", build123d.export_brep)
    assert write_brep(shape, archive)
    label = QLabel("HLR 技术验证：等待计算，当前 MyCAD 文档不受影响")
    label.setWindowTitle("MyCAD T0 — HLR heartbeat probe")
    label.resize(680, 120)
    qtbot.addWidget(label)
    label.show()
    times: list[float] = []
    completed: list[ExecutionResult] = []
    timer = QTimer()
    timer.setInterval(100)

    def tick() -> None:
        times.append(perf_counter())
        label.setText(f"HLR 技术验证：UI 心跳 {len(times)}，计算路径 {use_process=}")

    timer.timeout.connect(tick)
    unit = SerializedExecutionUnit()
    unit.set_session(1)
    # Spawn, never fork a running Qt/OCCT process. Include cold start in heartbeat.
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))

    def action() -> dict[str, object]:
        if use_process:
            return pool.submit(benchmark_brep, str(archive)).result(timeout=120)
        return benchmark_brep(str(archive))

    timer.start()
    qtbot.wait(150)
    times.append(perf_counter())
    start = perf_counter()
    try:
        assert unit.submit(
            action, operation="HLR probe", session_id=1, on_complete=completed.append
        )
        qtbot.waitUntil(lambda: bool(completed), timeout=120000)
        times.append(perf_counter())
        assert completed[0].error is None
    finally:
        timer.stop()
        unit.shutdown(wait_for_running=True)
        pool.shutdown(wait=True, cancel_futures=True)
    elapsed = perf_counter() - start
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    metrics = cast("dict[str, object]", completed[0].value)
    report = {
        **metrics,
        "mode": "process" if use_process else "thread",
        "platform": platform.platform(),
        "wall_including_startup_s": elapsed,
        "heartbeat_samples": len(times),
        "max_gap_s": max(gaps),
    }
    label.setText(
        f"HLR {report['mode']} / {metrics['edges']} edges\n"
        f"max UI gap {max(gaps):.3f}s / p50 {metrics['p50_s']}s"
    )
    screenshot = tmp_path / "heartbeat.png"
    assert label.grab().save(str(screenshot))
    report["screenshot"] = str(screenshot)
    print(json.dumps(report, indent=2))
    if use_process:
        assert metrics["pid"] != os.getpid()
        assert max(gaps) <= 0.25, "Process HLR must not stall the GUI heartbeat"
        assert cast("float", metrics["p95_sample_s"]) <= 3, "Three views exceeded T0 target"
