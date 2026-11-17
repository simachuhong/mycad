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
from typing import TYPE_CHECKING, cast

import build123d

from mycad.core.drawing_detail import clip_detail_projection
from mycad.core.drawing_projection import (
    DrawingProjectionRequest,
    DrawingSourceSnapshot,
    ProjectionResult,
    ViewBasis,
)
from mycad.geom.drawing_detail import clip_detail_exact
from mycad.geom.drawing_projection import ProjectionSources, Shape, project_shape
from mycad.geom.drawing_section import project_section

if TYPE_CHECKING:
    from mycad.core.drawing_detail import DetailRegion
    from mycad.core.drawing_section import SectionPlane

_shape: Shape | None = None
_sources: ProjectionSources | None = None
_fingerprint = ""
_cache: dict[
    tuple[ViewBasis, SectionPlane | None, float, DetailRegion | None], ProjectionResult
] = {}


def _ready() -> int:
    return os.getpid()


def _project(
    snapshot: DrawingSourceSnapshot, requests: tuple[DrawingProjectionRequest, ...]
) -> tuple[ProjectionResult, ...]:
    global _shape, _fingerprint, _sources
    if any(r.source != "current_part" for r in requests):
        raise ValueError("HLR requires a solid source")
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
        key = (request.basis, request.section, request.hatch_spacing_mm, request.detail)
        if key not in _cache:
            if len(_cache) >= 24:
                _cache.clear()
            try:
                if request.section is not None:
                    if not isinstance(_shape, build123d.Compound | build123d.Solid):
                        raise ValueError("section requires a solid source")
                    _cache[key] = project_section(
                        _shape, request.section, request, request.hatch_spacing_mm
                    ).projection
                elif request.detail is not None:
                    parent = project_shape(_shape, request, _sources)
                    _cache[key] = clip_detail_projection(
                        parent,
                        request.detail,
                        request.view_id,
                        request.generation,
                        clipper=clip_detail_exact,
                    )
                else:
                    _cache[key] = project_shape(_shape, request, _sources)
            except Exception as error:
                kind = (
                    "剖视" if request.section is not None else "详图" if request.detail else "投影"
                )
                results.append(
                    ProjectionResult(
                        request.view_id,
                        request.source_fingerprint,
                        request.generation,
                        (),
                        (f"{kind}生成失败：{error}",),
                    )
                )
                continue
        results.append(replace(_cache[key], view_id=request.view_id, generation=request.generation))
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
