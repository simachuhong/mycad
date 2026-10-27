# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Semantic topology binding and safe re-query behavior."""

from __future__ import annotations

import pytest
from build123d import Box, Compound, Cylinder, Pos

from mycad.core.exceptions import TopologyReferenceError
from mycad.core.identity import RuntimeIdentityScope
from mycad.core.semantic_refs import EdgePredicate, FacePredicate
from mycad.geom.kernel import BuildKernel
from mycad.geom.selectors import (
    bind_semantic_edge,
    bind_semantic_face,
    resolve_semantic_edge,
    resolve_semantic_face,
)


def test_max_face_is_requeried_from_predicate_after_size_change() -> None:
    scope = RuntimeIdentityScope()
    owner = scope.new_feature_id()
    first = Box(10, 10, 2)
    reference, first_face = bind_semantic_face(
        scope,
        owner,
        "max_face",
        FacePredicate(surface="plane", axis="+Z"),
        first,
        "feature.hole",
        "target_face",
    )
    assert first_face.area == pytest.approx(100)

    scope.invalidate_topology()
    new_owner = scope.new_feature_id()
    changed = Box(12, 12, 2)
    updated_ref, _ = bind_semantic_face(
        scope,
        new_owner,
        "max_face",
        FacePredicate(surface="plane", axis="+Z"),
        changed,
        "feature.hole",
        "target_face",
    )
    new_face, evidence = resolve_semantic_face(
        scope, updated_ref, new_owner, changed, "feature.hole", "target_face"
    )

    assert new_face.area == pytest.approx(144)
    assert evidence.selection_rule == "max-area"
    with pytest.raises(TopologyReferenceError) as excinfo:
        resolve_semantic_face(scope, reference, new_owner, changed, "feature.hole", "target_face")
    assert excinfo.value.reason == "drift"


def test_stale_topology_generation_reports_drift_and_parameter_location() -> None:
    scope = RuntimeIdentityScope()
    owner = scope.new_feature_id()
    reference, _ = bind_semantic_face(
        scope,
        owner,
        "max_face",
        FacePredicate(surface="plane", axis="+Z"),
        Box(10, 10, 2),
        "feature.hole",
        "target_face",
    )
    scope.invalidate_topology()

    with pytest.raises(TopologyReferenceError) as excinfo:
        resolve_semantic_face(
            scope, reference, owner, Box(12, 12, 2), "feature.hole", "target_face"
        )

    assert excinfo.value.reason == "drift"
    assert excinfo.value.command_id == "feature.hole"
    assert excinfo.value.parameter_path == "target_face"


def test_equal_maximum_faces_are_ambiguous_instead_of_rank_fallback() -> None:
    scope = RuntimeIdentityScope()
    owner = scope.new_feature_id()
    two_equal_solids = Compound(children=[Box(10, 10, 2), Pos(20, 0, 0) * Box(10, 10, 2)])

    with pytest.raises(TopologyReferenceError) as excinfo:
        bind_semantic_face(
            scope,
            owner,
            "max_face",
            FacePredicate(surface="plane", axis="+Z"),
            two_equal_solids,
            "modify.fillet",
            "edges[0].parent_faces[0]",
        )

    assert excinfo.value.reason == "ambiguous"
    assert excinfo.value.parameter_path == "edges[0].parent_faces[0]"


def test_live_reference_with_replaced_owner_reports_deleted() -> None:
    scope = RuntimeIdentityScope()
    original_owner = scope.new_feature_id()
    replacement_owner = scope.new_feature_id()
    part = Box(10, 10, 2)
    reference, _ = bind_semantic_face(
        scope,
        original_owner,
        "max_face",
        FacePredicate(surface="plane", axis="+Z"),
        part,
        "feature.hole",
        "target_face",
    )

    with pytest.raises(TopologyReferenceError) as excinfo:
        resolve_semantic_face(
            scope, reference, replacement_owner, part, "feature.hole", "target_face"
        )

    assert excinfo.value.reason == "deleted"


def test_unique_semantic_edge_can_be_requeried_in_same_generation() -> None:
    scope = RuntimeIdentityScope()
    owner = scope.new_feature_id()
    part = Cylinder(5, 2)
    predicate = EdgePredicate(
        parent_faces=(FacePredicate(surface="plane", axis="+Z"),),
        curve="circle",
    )
    reference, _ = bind_semantic_edge(
        scope, owner, "unique", predicate, part, "modify.fillet", "edges[0]"
    )
    edge, evidence = resolve_semantic_edge(
        scope, reference, owner, part, "modify.fillet", "edges[0]"
    )

    assert edge.geom_type.name == "CIRCLE"
    assert evidence.selection_rule == "unique-predicate"


def test_semantic_edge_binds_one_circular_edge_from_unique_parent() -> None:
    scope = RuntimeIdentityScope()
    owner = scope.new_feature_id()
    reference, edge = bind_semantic_edge(
        scope,
        owner,
        "unique",
        EdgePredicate(
            parent_faces=(FacePredicate(surface="plane", axis="+Z"),),
            curve="circle",
        ),
        Cylinder(5, 2),
        "modify.fillet",
        "edges[0]",
    )

    assert edge.geom_type.name == "CIRCLE"
    assert reference.owner_feature == owner


def test_kernel_assigns_feature_ids_and_expires_refs_on_state_change() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10, "size_y": 10, "size_z": 2})
    original_id = kernel.current_feature_id
    assert original_id is not None
    assert kernel.feature_ids == (original_id,)
    reference, _ = kernel.bind_semantic_face(
        "max_face",
        FacePredicate(surface="plane", axis="+Z"),
        "feature.hole",
        "target_face",
    )

    kernel.reset()
    kernel.apply("feature.box", {"size_x": 12, "size_y": 12, "size_z": 2})
    replayed_id = kernel.current_feature_id

    assert replayed_id is not None and replayed_id != original_id
    assert kernel.feature_ids == (replayed_id,)
    with pytest.raises(TopologyReferenceError) as excinfo:
        kernel.resolve_semantic_face(reference, "feature.hole", "target_face")
    assert excinfo.value.reason == "drift"
