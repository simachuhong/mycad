# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Desired projection generations, independent of worker timing and Qt delivery."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from mycad.core.drawing_projection import DrawingProjectionRequest, ProjectionResult, ViewBasis

ViewStatus = Literal["clean", "stale", "updating", "failed"]


@dataclass(frozen=True, slots=True)
class ProjectionBatch:
    session_id: int
    requests: tuple[DrawingProjectionRequest, ...]


class ProjectionUpdates:
    def __init__(self) -> None:
        self.session_id = -1
        self.results: dict[UUID, ProjectionResult] = {}
        self._desired: dict[UUID, DrawingProjectionRequest] = {}
        self._failed: dict[UUID, tuple[int, str]] = {}
        self._cancelled: set[tuple[UUID, int]] = set()
        self._active: ProjectionBatch | None = None
        self._generation = 0

    def sync(self, session_id: int, fingerprint: str, bases: Mapping[UUID, ViewBasis]) -> None:
        if session_id != self.session_id:
            self.session_id = session_id
            self.results.clear()
            self._desired.clear()
            self._failed.clear()
            self._cancelled.clear()
            self._active = None
        for identity in set(self._desired) - set(bases):
            self._desired.pop(identity)
            self.results.pop(identity, None)
            self._failed.pop(identity, None)
            self._cancelled = {pair for pair in self._cancelled if pair[0] != identity}
        for identity, basis in bases.items():
            previous = self._desired.get(identity)
            if (
                previous is not None
                and previous.source_fingerprint == fingerprint
                and previous.basis == basis
            ):
                continue
            self._generation += 1
            self._desired[identity] = DrawingProjectionRequest(
                identity, fingerprint, self._generation, basis
            )
            self._failed.pop(identity, None)
            self._cancelled = {pair for pair in self._cancelled if pair[0] != identity}

    def status(self, identity: UUID) -> ViewStatus:
        request = self._desired.get(identity)
        if request is None:
            return "stale"
        failure = self._failed.get(identity)
        if failure is not None and failure[0] == request.generation:
            return "failed"
        result = self.results.get(identity)
        if result is not None and self._matches(request, result):
            return "clean"
        if (identity, request.generation) in self._cancelled:
            return "stale"
        if self._active is not None and request in self._active.requests:
            return "updating"
        return "stale"

    @staticmethod
    def _matches(request: DrawingProjectionRequest, result: ProjectionResult) -> bool:
        return (
            request.view_id == result.view_id
            and request.source_fingerprint == result.source_fingerprint
            and request.generation == result.generation
        )

    @property
    def has_pending(self) -> bool:
        return any(
            self.status(identity) == "stale"
            and (identity, request.generation) not in self._cancelled
            for identity, request in self._desired.items()
        )

    def begin(self) -> ProjectionBatch | None:
        if self._active is not None:
            return None
        requests = tuple(
            request
            for identity, request in self._desired.items()
            if self.status(identity) == "stale"
            and (identity, request.generation) not in self._cancelled
        )
        if not requests:
            return None
        self._active = ProjectionBatch(self.session_id, requests)
        return self._active

    def finish(
        self,
        batch: ProjectionBatch,
        results: tuple[ProjectionResult, ...],
        *,
        error: str | None = None,
    ) -> int:
        if batch is not self._active or batch.session_id != self.session_id:
            return 0
        self._active = None
        received = {result.view_id: result for result in results}
        accepted = 0
        for request in batch.requests:
            identity = request.view_id
            if (
                self._desired.get(identity) != request
                or (identity, request.generation) in self._cancelled
            ):
                continue
            result = received.get(identity)
            if error is None and result is not None and self._matches(request, result):
                if result.diagnostics:
                    self._failed[identity] = (request.generation, "; ".join(result.diagnostics))
                    continue
                self.results[identity] = result
                accepted += 1
            else:
                self._failed[identity] = (
                    request.generation,
                    error or "Projection response missing or outdated",
                )
        return accepted

    def failure_message(self, identity: UUID) -> str:
        return self._failed.get(identity, (0, ""))[1]

    def cancel(self) -> None:
        self._cancelled.update(
            (r.view_id, r.generation)
            for r in self._desired.values()
            if self.status(r.view_id) != "clean"
        )

    def retry(self) -> None:
        for identity, request in tuple(self._desired.items()):
            if self.status(identity) in ("failed", "stale"):
                self._generation += 1
                self._desired[identity] = DrawingProjectionRequest(
                    identity, request.source_fingerprint, self._generation, request.basis
                )
        self._failed.clear()
        self._cancelled.clear()
