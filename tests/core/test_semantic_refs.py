# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral semantic-reference descriptors and their ownership contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from mycad.core.identity import RuntimeIdentityScope
from mycad.core.semantic_refs import (
    EdgePredicate,
    FacePredicate,
    SemanticEdgeRef,
    SemanticFaceRef,
)


def _assign_attribute(target: object, name: str, value: object) -> None:
    setattr(target, name, value)


def test_semantic_face_ref_is_owned_and_has_no_rank_identity() -> None:
    scope = RuntimeIdentityScope()
    reference = SemanticFaceRef(
        owner_feature=scope.new_feature_id(),
        role="max_face",
        predicate=FacePredicate(surface="plane", axis="+Z"),
        topology_id=scope.new_topology_id(),
    )

    assert reference.predicate.surface == "plane"
    assert not hasattr(reference.predicate, "rank")
    with pytest.raises(FrozenInstanceError):
        _assign_attribute(reference, "role", "other")


def test_semantic_edge_ref_keeps_parent_face_predicate() -> None:
    scope = RuntimeIdentityScope()
    reference = SemanticEdgeRef(
        owner_feature=scope.new_feature_id(),
        role="unique",
        predicate=EdgePredicate(
            parent_faces=(FacePredicate(surface="plane", axis="+Z"),),
            curve="circle",
        ),
        topology_id=scope.new_topology_id(),
    )

    assert reference.predicate.curve == "circle"
    assert reference.predicate.parent_faces[0].axis == "+Z"


def test_semantic_predicate_rejects_invalid_or_empty_descriptors() -> None:
    with pytest.raises(ValueError, match="plane.*axis"):
        FacePredicate(surface="plane", axis=None)
    with pytest.raises(ValueError, match="parent face"):
        EdgePredicate(parent_faces=())
