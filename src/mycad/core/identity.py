# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Ephemeral, backend-neutral identities for one live document runtime."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from mycad.core.exceptions import TopologyReferenceError

__all__ = [
    "BodyId",
    "FeatureId",
    "HistoryOrdinal",
    "RuntimeIdentityScope",
    "TopologyId",
]


@dataclass(frozen=True, slots=True)
class FeatureId:
    """Runtime identity of a history feature, unrelated to its ordinal."""

    value: UUID
    generation: int


@dataclass(frozen=True, slots=True)
class BodyId:
    """Runtime identity of a current modeled body, minted in one replay generation."""

    value: UUID
    generation: int


@dataclass(frozen=True, slots=True)
class TopologyId:
    """Runtime identity for one face or edge topology reference."""

    value: UUID
    generation: int


@dataclass(frozen=True, slots=True)
class HistoryOrdinal:
    """Zero-based command-history position; never a geometry identity."""

    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or self.value < 0:
            raise ValueError("history ordinal must be a nonnegative integer")


class RuntimeIdentityScope:
    """Allocate unique identities and expire topology refs on replay.

    IDs are deliberately runtime-only. A successful replay advances the
    generation and expires every topology reference; IDs are never derived
    from history ordinals or recycled after invalidation.
    """

    def __init__(self) -> None:
        self._generation = 0
        self._topology_ids: set[TopologyId] = set()

    @property
    def generation(self) -> int:
        """Current runtime generation, incremented when all topology expires."""

        return self._generation

    def new_feature_id(self) -> FeatureId:
        """Allocate an opaque feature ID in the current generation."""

        return FeatureId(value=uuid4(), generation=self._generation)

    def new_body_id(self) -> BodyId:
        """Allocate an opaque body ID in the current generation."""

        return BodyId(value=uuid4(), generation=self._generation)

    def new_topology_id(self) -> TopologyId:
        """Allocate a live topology ID in the current generation."""

        identity = TopologyId(value=uuid4(), generation=self._generation)
        self._topology_ids.add(identity)
        return identity

    def invalidate_topology(self, identity: TopologyId | None = None) -> None:
        """Expire one topology ID or all topology IDs after replay.

        Invalidating all topology advances the generation, so subsequent
        feature, body, and topology IDs cannot be confused with earlier
        replay state. Invalidating one topology leaves unrelated references
        in the current generation live.
        """

        if identity is None:
            self._topology_ids.clear()
            self._generation += 1
            return
        self._topology_ids.discard(identity)

    def is_current_topology(self, identity: TopologyId) -> bool:
        """Return whether a topology ID still refers to this live generation."""

        return identity.generation == self._generation and identity in self._topology_ids

    def require_current_topology(
        self,
        identity: TopologyId,
        command_id: str | None = None,
        parameter_path: str | None = None,
    ) -> None:
        """Raise the existing structured topology error for an expired ID."""

        if not self.is_current_topology(identity):
            raise TopologyReferenceError(
                "stale runtime topology identity",
                command_id=command_id,
                reason="drift",
                parameter_path=parameter_path,
            )
