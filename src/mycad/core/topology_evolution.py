# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Backend-neutral result vocabulary for one topology-changing operation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TopologyKind = Literal["face", "edge"]
TopologyRelation = Literal[
    "preserved", "modified", "generated", "split", "merged", "deleted", "unknown"
]


@dataclass(frozen=True, slots=True)
class TopologyTransition:
    """How one source face or edge maps to the final operation result."""

    kind: TopologyKind
    source_shape_index: int
    source_index: int
    relation: TopologyRelation
    targets: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TopologyEvolution:
    """Operation-local mapping; indices expire as soon as another operation runs."""

    transitions: tuple[TopologyTransition, ...]

    def face_transition(self, source_shape_index: int, source_index: int) -> TopologyTransition:
        return self._transition("face", source_shape_index, source_index)

    def edge_transition(self, source_shape_index: int, source_index: int) -> TopologyTransition:
        return self._transition("edge", source_shape_index, source_index)

    def _transition(
        self, kind: TopologyKind, source_shape_index: int, source_index: int
    ) -> TopologyTransition:
        for transition in self.transitions:
            if (
                transition.kind == kind
                and transition.source_shape_index == source_shape_index
                and transition.source_index == source_index
            ):
                return transition
        raise KeyError((kind, source_shape_index, source_index))


__all__ = ["TopologyEvolution", "TopologyKind", "TopologyRelation", "TopologyTransition"]
