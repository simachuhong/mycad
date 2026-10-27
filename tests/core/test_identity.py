# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Runtime identity lifecycle contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from mycad.core.exceptions import TopologyReferenceError
from mycad.core.identity import (
    BodyId,
    FeatureId,
    HistoryOrdinal,
    RuntimeIdentityScope,
    TopologyId,
)


def _assign_attribute(target: object, name: str, value: object) -> None:
    setattr(target, name, value)


def test_identity_value_types_are_frozen_and_not_interchangeable() -> None:
    scope = RuntimeIdentityScope()
    feature_id = scope.new_feature_id()
    body_id = scope.new_body_id()
    topology_id = scope.new_topology_id()
    ordinal = HistoryOrdinal(0)

    assert isinstance(feature_id, FeatureId)
    assert isinstance(body_id, BodyId)
    assert isinstance(topology_id, TopologyId)
    assert feature_id != body_id
    assert topology_id != ordinal
    with pytest.raises(FrozenInstanceError):
        _assign_attribute(feature_id, "generation", 4)


def test_replay_generation_allocates_fresh_runtime_identities() -> None:
    scope = RuntimeIdentityScope()
    previous = (scope.new_feature_id(), scope.new_body_id(), scope.new_topology_id())
    scope.invalidate_topology()
    current = (scope.new_feature_id(), scope.new_body_id(), scope.new_topology_id())

    assert scope.generation == 1
    assert all(old != new for old, new in zip(previous, current, strict=True))
    assert all(identity.generation == 0 for identity in previous)
    assert all(identity.generation == 1 for identity in current)


def test_invalidated_topology_is_rejected_and_never_reused() -> None:
    scope = RuntimeIdentityScope()
    stale = scope.new_topology_id()
    scope.invalidate_topology(stale)

    with pytest.raises(TopologyReferenceError, match="stale"):
        scope.require_current_topology(stale, command_id="feature.hole")

    replacement = scope.new_topology_id()
    assert replacement != stale
    assert scope.is_current_topology(replacement)


def test_history_ordinal_is_nonnegative_and_distinct_from_runtime_identity() -> None:
    assert HistoryOrdinal(3).value == 3
    with pytest.raises(ValueError):
        HistoryOrdinal(-1)
    assert HistoryOrdinal(3) != RuntimeIdentityScope().new_feature_id()
