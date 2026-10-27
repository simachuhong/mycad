# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Persistent spawned worker accepts immutable geometry snapshots only."""

from uuid import uuid4

from mycad.app import build_app, new_document
from mycad.core.drawing_projection import DrawingProjectionRequest, LineCurve
from mycad.geom.drawing_worker import DrawingProjectionWorker


def test_snapshot_isolated_from_later_model_and_worker_is_reused() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 24, "size_z": 8})
    snapshot = services.kernel.drawing_snapshot()
    loaded.bus.execute("feature.box", {"size_x": 80, "size_y": 24, "size_z": 8})
    worker = DrawingProjectionWorker()
    try:
        pid = worker.prewarm().result(timeout=45)
        request = DrawingProjectionRequest(uuid4(), snapshot.source_fingerprint, 7)
        result = worker.submit(snapshot, (request,)).result(timeout=45)
        assert worker.prewarm().result(timeout=5) == pid
        assert result[0].generation == 7
        assert any(
            isinstance(c.geometry, LineCurve) and c.geometry.length == 40 for c in result[0].curves
        )
        assert not any(
            isinstance(c.geometry, LineCurve) and c.geometry.length == 80 for c in result[0].curves
        )
        assert worker.submit(snapshot, (request,)).result(timeout=5) == result
    finally:
        worker.close()


def test_complete_projection_payload_timing() -> None:
    from collections.abc import Callable
    from io import BytesIO
    from time import perf_counter
    from typing import cast

    import build123d
    from build123d import Compound, Cylinder, Pos

    from mycad.core.drawing_projection import DrawingSourceSnapshot, ViewBasis

    shape = Compound(
        children=[Pos(x * 5, y * 5, 0) * Cylinder(2, 8) for x in range(30) for y in range(10)]
    )
    stream = BytesIO()
    write_brep = cast("Callable[[Compound, BytesIO], bool]", build123d.export_brep)
    assert write_brep(shape, stream)
    snapshot = DrawingSourceSnapshot("900-edge-fixture", stream.getvalue())
    requests = tuple(
        DrawingProjectionRequest(
            uuid4(), snapshot.source_fingerprint, 1, ViewBasis.from_normal_up(n, u)
        )
        for n, u in [((0, 0, 1), (0, 1, 0)), ((0, -1, 0), (0, 0, 1)), ((-1, 0, 0), (0, 0, 1))]
    )
    worker = DrawingProjectionWorker()
    try:
        worker.prewarm().result(timeout=45)
        start = perf_counter()
        results = worker.submit(snapshot, requests).result(timeout=120)
        elapsed = perf_counter() - start
        print(
            f"complete 900-edge DTO pipeline: {elapsed:.3f}s, curves={sum(len(r.curves) for r in results)}"
        )
        assert len(results) == 3
        assert all(not r.diagnostics for r in results)
        assert elapsed <= 3, "Full DTO pipeline exceeds the warm three-view target"
    finally:
        worker.close()
