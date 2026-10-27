# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Persistent spawned HLR process with bounded caches and explicit lifecycle."""

from __future__ import annotations

import multiprocessing
import os
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import build123d

from mycad.core.drawing_projection import (
    DrawingProjectionRequest,
    DrawingSourceSnapshot,
    ProjectionResult,
    ViewBasis,
)
from mycad.geom.drawing_projection import ProjectionSources, Shape, project_shape

_shape: Shape | None = None
_sources: ProjectionSources | None = None
_fingerprint = ""
_cache: dict[ViewBasis, ProjectionResult] = {}


def _ready() -> int:
    return os.getpid()


def _project(
    snapshot: DrawingSourceSnapshot, requests: tuple[DrawingProjectionRequest, ...]
) -> tuple[ProjectionResult, ...]:
    global _shape, _fingerprint, _sources
    if any(r.source_fingerprint != snapshot.source_fingerprint for r in requests):
        raise ValueError("Projection request does not match source snapshot")
    if _fingerprint != snapshot.source_fingerprint or _shape is None:
        with TemporaryDirectory(prefix="mycad-hlr-") as directory:
            path = Path(directory) / "source.brep"
            path.write_bytes(snapshot.brep)
            load = cast("Callable[[str], Shape]", build123d.import_brep)
            _shape = load(str(path))
        _sources = ProjectionSources(_shape)
        _fingerprint = snapshot.source_fingerprint
        _cache.clear()
    results: list[ProjectionResult] = []
    for request in requests:
        if request.basis not in _cache:
            if len(_cache) >= 24:
                _cache.clear()
            _cache[request.basis] = project_shape(_shape, request, _sources)
        results.append(
            replace(_cache[request.basis], view_id=request.view_id, generation=request.generation)
        )
    return tuple(results)


class DrawingProjectionWorker:
    """Call submit only with snapshots taken on the serialized model worker.

    Future completion is not permission to publish: UI checks session,
    fingerprint, view and generation. A failed pool can be replaced via restart.
    """

    def __init__(self) -> None:
        self._pool = ProcessPoolExecutor(
            max_workers=1, mp_context=multiprocessing.get_context("spawn")
        )
        self._closed = False

    def prewarm(self) -> Future[int]:
        return self._pool.submit(_ready)

    def submit(
        self, snapshot: DrawingSourceSnapshot, requests: tuple[DrawingProjectionRequest, ...]
    ) -> Future[tuple[ProjectionResult, ...]]:
        if self._closed:
            raise RuntimeError("Drawing worker is closed")
        return self._pool.submit(_project, snapshot, requests)

    def restart(self) -> None:
        self.close()
        self._pool = ProcessPoolExecutor(
            max_workers=1, mp_context=multiprocessing.get_context("spawn")
        )
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._pool.shutdown(wait=False, cancel_futures=True)
