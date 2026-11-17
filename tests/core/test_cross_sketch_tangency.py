# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Stable cross-sketch tangency records and dependency components."""

import math
from typing import Literal
from uuid import uuid4

import pytest

from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Sketch, WorkPlaneFrame


def test_local_tangent_similarity_rejects_independent_geometry_changes() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import rebind_retained_local_tangencies
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    before = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle), (relation,))
    scaled_line = replace(line, end_mm=(20, 0))
    shifted_circle = replace(circle, center_mm=(11, 4), radius_mm=4)
    after = replace(before, entities=(scaled_line, shifted_circle))
    with pytest.raises(ValueError, match="无法确认打断片段"):
        rebind_retained_local_tangencies(
            before, after, allow_split_lines=True, allow_joint_similarity=True
        )


def test_relation_mapping_roundtrip_preserves_owner_and_branch() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency

    first = CrossSketchRef(uuid4().hex, uuid4().hex)
    second = CrossSketchRef(uuid4().hex, uuid4().hex)
    relation = CrossSketchTangency(uuid4().hex, first, second, "external")
    assert CrossSketchTangency.from_mapping(relation.to_mapping()) == relation


def test_cross_sketch_segment_reference_roundtrip_and_validation() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef

    sketch_id, entity_id = uuid4().hex, uuid4().hex
    legacy = CrossSketchRef(sketch_id, entity_id)
    assert legacy.to_mapping() == {"sketch_id": sketch_id, "entity_id": entity_id}
    ref = CrossSketchRef(sketch_id, entity_id, segment_index=2)
    assert ref.to_mapping() == {"sketch_id": sketch_id, "entity_id": entity_id, "segment_index": 2}
    assert CrossSketchRef.from_mapping(ref.to_mapping()) == ref
    for bad in (-1, True, 1.2, "1"):
        with pytest.raises(ValueError):
            CrossSketchRef.from_mapping(
                {"sketch_id": sketch_id, "entity_id": entity_id, "segment_index": bad}
            )


def test_segment_relation_uses_new_command_schema_without_changing_old_versions() -> None:
    from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
    from mycad.commands.validation import validate_params
    from mycad.core.exceptions import ValidationError

    relation = {
        "relation_id": uuid4().hex,
        "first": {"sketch_id": uuid4().hex, "entity_id": uuid4().hex, "segment_index": 0},
        "second": {"sketch_id": uuid4().hex, "entity_id": uuid4().hex},
        "branch": "line_left",
    }
    params: dict[str, object] = {"relation": relation, "revisions": []}
    for version in (1, 2):
        spec = next(
            s
            for s in BUILTIN_COMMAND_SPECS
            if s.id == "drawing.tangency.add" and s.version == version
        )
        with pytest.raises(ValidationError):
            validate_params(spec, params, defs=COMMAND_SCHEMA_DEFS)
    spec = next(
        s for s in BUILTIN_COMMAND_SPECS if s.id == "drawing.tangency.add" and s.version == 3
    )
    assert validate_params(spec, params, defs=COMMAND_SCHEMA_DEFS)["relation"] == relation


def test_draft_segment_relation_is_gated_by_new_create_and_revision_versions() -> None:
    from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
    from mycad.commands.validation import validate_params
    from mycad.core.exceptions import ValidationError

    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (10, 0)),))
    relation = {
        "relation_id": uuid4().hex,
        "first": {"sketch_id": uuid4().hex, "entity_id": uuid4().hex, "segment_index": 0},
        "second": {"sketch_id": sketch.sketch_id, "entity_id": sketch.entities[0].entity_id},
        "branch": "line_left",
    }
    params = {**sketch.to_state_mapping(), "cross_tangencies": [relation]}
    old = next(s for s in BUILTIN_COMMAND_SPECS if s.id == "sketch.create" and s.version == 9)
    new = next(s for s in BUILTIN_COMMAND_SPECS if s.id == "sketch.create" and s.version == 10)
    with pytest.raises(ValidationError):
        validate_params(old, params, defs=COMMAND_SCHEMA_DEFS)
    assert validate_params(new, params, defs=COMMAND_SCHEMA_DEFS)["cross_tangencies"] == [relation]
    state = sketch.to_state_mapping()
    revision = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": "0" * 64,
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    batch = {"revisions": [revision], "cross_tangencies": [relation]}
    old_revision = next(
        s for s in BUILTIN_COMMAND_SPECS if s.id == "drawing.sketch.revise" and s.version == 3
    )
    new_revision = next(
        s for s in BUILTIN_COMMAND_SPECS if s.id == "drawing.sketch.revise" and s.version == 5
    )
    with pytest.raises(ValidationError):
        validate_params(old_revision, batch, defs=COMMAND_SCHEMA_DEFS)
    assert validate_params(new_revision, batch, defs=COMMAND_SCHEMA_DEFS)["cross_tangencies"] == [
        relation
    ]


def test_cross_sketch_tangency_validates_actual_finite_polyline_arc() -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )
    from mycad.core.sketch import PolylineEntity

    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curved,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, curved.entity_id, 0),
        CrossSketchRef(second.sketch_id, line.entity_id),
        "line_left",
    )
    validate_tangency_component((first, second), (relation,), first.sketch_id)
    wrong_segment = CrossSketchTangency(
        relation.relation_id,
        CrossSketchRef(first.sketch_id, curved.entity_id, 1),
        relation.second,
        "line_left",
    )
    with pytest.raises(ValueError):
        validate_tangency_component((first, second), (wrong_segment,), first.sketch_id)
    invalid_index = CrossSketchTangency(
        relation.relation_id,
        CrossSketchRef(first.sketch_id, curved.entity_id, 9),
        relation.second,
        "line_left",
    )
    with pytest.raises(ValueError):
        validate_tangency_component((first, second), (invalid_index,), first.sketch_id)


def test_relation_requires_different_sketches_and_valid_branch() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency

    sketch_id = uuid4().hex
    first = CrossSketchRef(sketch_id, uuid4().hex)
    second = CrossSketchRef(sketch_id, uuid4().hex)
    with pytest.raises(ValueError):
        CrossSketchTangency(uuid4().hex, first, second, "external")
    with pytest.raises(ValueError):
        CrossSketchTangency.from_mapping(
            {
                "relation_id": uuid4().hex,
                "first": first.to_mapping(),
                "second": CrossSketchRef(uuid4().hex, uuid4().hex).to_mapping(),
                "branch": "unspecified",
            }
        )


def test_component_follows_relations_through_cycles_but_not_other_components() -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        tangency_component,
    )

    a, b, c, d, e = (uuid4().hex for _ in range(5))

    def relation(first: str, second: str) -> CrossSketchTangency:
        return CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(first, uuid4().hex),
            CrossSketchRef(second, uuid4().hex),
            "external",
        )

    connected = (relation(a, b), relation(b, c), relation(c, a))
    other = relation(d, e)
    sketches, relations = tangency_component((other, *connected), a)
    assert sketches == tuple(sorted((a, b, c)))
    assert relations == tuple(sorted(item.relation_id for item in connected))


def test_component_rejects_duplicate_relation_ids() -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        tangency_component,
    )

    first = CrossSketchRef(uuid4().hex, uuid4().hex)
    second = CrossSketchRef(uuid4().hex, uuid4().hex)
    relation = CrossSketchTangency(uuid4().hex, first, second, "external")
    with pytest.raises(ValueError):
        tangency_component((relation, relation), first.sketch_id)


def test_project_entity_into_rotated_coplanar_frame() -> None:
    from mycad.core.cross_sketch_tangency import project_tangent_entity

    source = WorkPlaneFrame((10, 5, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    line = LineEntity(uuid4().hex, (0, 0), (2, 0), construction=True)
    result = project_tangent_entity(line, source, WorkPlaneFrame.xy())
    assert isinstance(result, LineEntity)
    assert result.start_mm == pytest.approx((10, 5)) and result.end_mm == pytest.approx((10, 7))
    assert result.entity_id == line.entity_id and result.construction


def test_project_arc_from_opposite_normal_reverses_sweep() -> None:
    from mycad.core.cross_sketch_tangency import project_tangent_entity

    source = WorkPlaneFrame((0, 0, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
    arc = ArcEntity(uuid4().hex, (0, 0), 2, 0, 90)
    result = project_tangent_entity(arc, source, WorkPlaneFrame.xy())
    assert isinstance(result, ArcEntity)
    assert result.center_mm == (0, 0)
    assert result.start_angle_deg == pytest.approx(180)
    assert result.sweep_angle_deg == pytest.approx(-90)


def test_project_curved_polyline_preserves_world_geometry_and_handedness() -> None:
    from mycad.core.cross_sketch_tangency import project_polyline_entity
    from mycad.core.sketch import PolylineEntity

    polyline = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 3)), bulges=(0.5, -0.25))
    for source, expected in (
        (WorkPlaneFrame((10, 5, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1)), (0.5, -0.25)),
        (WorkPlaneFrame((0, 0, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1)), (-0.5, 0.25)),
    ):
        result = project_polyline_entity(polyline, source, WorkPlaneFrame.xy())
        assert result.bulges == expected
        for before, after in zip(polyline.points_mm, result.points_mm, strict=True):
            assert WorkPlaneFrame.xy().local_to_world(after) == pytest.approx(
                source.local_to_world(before)
            )
        assert project_polyline_entity(result, WorkPlaneFrame.xy(), source) == polyline
    offset = WorkPlaneFrame((0, 0, 1), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    with pytest.raises(ValueError, match="共面"):
        project_polyline_entity(polyline, offset, WorkPlaneFrame.xy())


def test_project_rejects_non_coplanar_frames() -> None:
    from mycad.core.cross_sketch_tangency import project_tangent_entity

    source = WorkPlaneFrame((0, 0, 1), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    with pytest.raises(ValueError, match="共面"):
        project_tangent_entity(line, source, WorkPlaneFrame.xy())


def test_project_rejects_slightly_tilted_plane() -> None:
    import math

    from mycad.core.cross_sketch_tangency import project_tangent_entity

    angle = 1e-5
    source = WorkPlaneFrame(
        (0, 0, 0),
        (1, 0, 0),
        (0, math.cos(angle), math.sin(angle)),
        (0, -math.sin(angle), math.cos(angle)),
    )
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    with pytest.raises(ValueError, match="共面"):
        project_tangent_entity(line, source, WorkPlaneFrame.xy())


def test_resolve_component_checks_owner_geometry_and_branch() -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        resolve_tangency_component,
    )

    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (10, 0)),))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 2), 2),))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, first.entities[0].entity_id),
        CrossSketchRef(second.sketch_id, second.entities[0].entity_id),
        "line_left",
    )
    sketches, relations = resolve_tangency_component((second, first), (relation,), first.sketch_id)
    assert {sketch.sketch_id for sketch in sketches} == {first.sketch_id, second.sketch_id}
    assert relations == (relation,)


def test_resolve_component_rejects_dangling_reference() -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        resolve_tangency_component,
    )

    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (10, 0)),))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 2), 2),))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, first.entities[0].entity_id),
        CrossSketchRef(second.sketch_id, uuid4().hex),
        "line_left",
    )
    with pytest.raises(ValueError, match="不存在"):
        resolve_tangency_component((first, second), (relation,), first.sketch_id)


def test_resolve_component_rejects_branch_mismatch_and_non_coplanarity() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        resolve_tangency_component,
    )

    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (10, 0)),))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 2), 2),))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, first.entities[0].entity_id),
        CrossSketchRef(second.sketch_id, second.entities[0].entity_id),
        "external",
    )
    with pytest.raises(ValueError, match="分支"):
        resolve_tangency_component((first, second), (relation,), first.sketch_id)
    offset = WorkPlaneFrame((0, 0, 1), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    with pytest.raises(ValueError, match="共面"):
        resolve_tangency_component(
            (first, replace(second, frame=offset)),
            (replace(relation, branch="line_left"),),
            first.sketch_id,
        )


def test_validate_component_requires_tangency_and_selected_line_side() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )

    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (-5, 0), (5, 0)),))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 2), 2),))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, first.entities[0].entity_id),
        CrossSketchRef(second.sketch_id, second.entities[0].entity_id),
        "line_left",
    )
    validate_tangency_component((first, second), (relation,), first.sketch_id)
    with pytest.raises(ValueError, match="分支"):
        validate_tangency_component(
            (first, second), (replace(relation, branch="line_right"),), first.sketch_id
        )
    moved = replace(second, entities=(replace(second.entities[0], center_mm=(0, 3)),))
    with pytest.raises(ValueError, match="相切"):
        validate_tangency_component((first, moved), (relation,), first.sketch_id)


def test_validate_component_rejects_contact_outside_finite_arc() -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )

    line = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    arc = ArcEntity(uuid4().hex, (0, 2), 2, 0, 90)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, arc.entity_id),
        "line_left",
    )
    with pytest.raises(ValueError, match="相切"):
        validate_tangency_component((first, second), (relation,), first.sketch_id)


@pytest.mark.parametrize("branch", ["first_contains_second", "second_contains_first"])
def test_validate_circular_internal_branch_tracks_which_circle_contains_the_other(
    branch: str,
) -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )

    first_circle = CircleEntity(uuid4().hex, (0, 0), 5)
    second_circle = CircleEntity(uuid4().hex, (3, 0), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first_circle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second_circle,))
    relation = CrossSketchTangency.from_mapping(
        {
            "relation_id": uuid4().hex,
            "first": CrossSketchRef(first.sketch_id, first_circle.entity_id).to_mapping(),
            "second": CrossSketchRef(second.sketch_id, second_circle.entity_id).to_mapping(),
            "branch": branch,
        }
    )
    if branch == "first_contains_second":
        validate_tangency_component((first, second), (relation,), first.sketch_id)
    else:
        with pytest.raises(ValueError, match="分支"):
            validate_tangency_component((first, second), (relation,), first.sketch_id)


def test_build_tangency_revisions_freezes_digest_and_geometry() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import build_tangency_revisions

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 3), 2),))
    revised_first = replace(first, entities=(replace(line, end_mm=(12, 0)),))
    revisions = build_tangency_revisions((first, second), (second, revised_first))
    assert len(revisions) == 1
    assert revisions[0]["sketch_id"] == first.sketch_id
    assert revisions[0]["base_state_sha256"] == first.local_state_digest()
    assert revisions[0]["entities"] == revised_first.to_state_mapping()["entities"]


def test_build_tangency_revisions_rejects_entity_identity_or_constraint_changes() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import build_tangency_revisions

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    revised = replace(sketch, entities=(replace(line, entity_id=uuid4().hex),))
    with pytest.raises(ValueError, match="身份"):
        build_tangency_revisions((sketch,), (revised,))


def test_infer_branch_from_finite_tangent_curves() -> None:
    from mycad.core.cross_sketch_tangency import infer_tangency_branch

    line = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    assert infer_tangency_branch(line, circle) == "line_left"
    outside = CircleEntity(uuid4().hex, (7, 2), 5)
    assert infer_tangency_branch(circle, outside) == "external"
    inner = CircleEntity(uuid4().hex, (1, 2), 1)
    assert infer_tangency_branch(circle, inner) == "first_contains_second"
    assert infer_tangency_branch(inner, circle) == "second_contains_first"
    with pytest.raises(ValueError, match="相切"):
        infer_tangency_branch(line, CircleEntity(uuid4().hex, (0, 3), 2))


def test_endpoint_tangency_roundtrip_and_legacy_mapping() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency

    first = CrossSketchRef(uuid4().hex, uuid4().hex)
    second = CrossSketchRef(uuid4().hex, uuid4().hex)
    legacy = CrossSketchTangency(uuid4().hex, first, second, "external")
    assert "first_endpoint" not in legacy.to_mapping()
    assert CrossSketchTangency.from_mapping(legacy.to_mapping()) == legacy
    connected = CrossSketchTangency(uuid4().hex, first, second, "external", second_endpoint="end")
    assert connected.to_mapping()["second_endpoint"] == "end"
    assert CrossSketchTangency.from_mapping(connected.to_mapping()) == connected
    for bad in (None, "middle", 1, True):
        with pytest.raises(ValueError):
            CrossSketchTangency.from_mapping({**legacy.to_mapping(), "first_endpoint": bad})


def test_endpoint_tangency_requires_contact_at_declared_arc_endpoint() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )

    circle = CircleEntity(uuid4().hex, (0, 0), 2)
    arc = ArcEntity(uuid4().hex, (4, 0), 2, 90, 90)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, circle.entity_id),
        CrossSketchRef(second.sketch_id, arc.entity_id),
        "external",
        second_endpoint="end",
    )
    validate_tangency_component((first, second), (relation,), first.sketch_id)
    with pytest.raises(ValueError, match="端点"):
        validate_tangency_component(
            (first, second), (replace(relation, second_endpoint="start"),), first.sketch_id
        )
    with pytest.raises(ValueError, match="端点"):
        validate_tangency_component(
            (first, second), (replace(relation, first_endpoint="start"),), first.sketch_id
        )


def test_endpoint_tangencies_require_new_command_versions() -> None:
    from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
    from mycad.commands.validation import validate_params
    from mycad.core.exceptions import ValidationError

    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (5, 0)),))
    relation = {
        "relation_id": uuid4().hex,
        "first": {"sketch_id": uuid4().hex, "entity_id": uuid4().hex, "segment_index": 0},
        "second": {"sketch_id": sketch.sketch_id, "entity_id": uuid4().hex},
        "branch": "line_left",
        "second_endpoint": "start",
    }
    state = sketch.to_state_mapping()
    revision = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": "0" * 64,
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    cases: tuple[tuple[str, int, int, dict[str, object]], ...] = (
        ("sketch.create", 11, 12, {**state, "cross_tangencies": [relation]}),
        ("drawing.sketch.revise", 6, 7, {"revisions": [revision], "cross_tangencies": [relation]}),
        ("drawing.tangency.add", 3, 4, {"revisions": [], "relation": relation}),
    )
    for command_id, old_version, new_version, params in cases:
        old = next(
            s for s in BUILTIN_COMMAND_SPECS if s.id == command_id and s.version == old_version
        )
        new = next(
            s for s in BUILTIN_COMMAND_SPECS if s.id == command_id and s.version == new_version
        )
        with pytest.raises(ValidationError):
            validate_params(old, params, defs=COMMAND_SCHEMA_DEFS)
        assert validate_params(new, params, defs=COMMAND_SCHEMA_DEFS) == params


def test_draft_endpoint_connection_resolves_without_changing_legacy_pair() -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import DraftConnectedEndpoint, draft_tangent_reference
    from mycad.core.sketch_constraints import SketchGeometryReference

    circle = CircleEntity(uuid4().hex, (0, 0), 2)
    arc = ArcEntity(uuid4().hex, (4, 0), 2, 90, 90)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    endpoint = DraftConnectedEndpoint(SketchGeometryReference(arc.entity_id, "geometry"), "end")
    assert draft_tangent_reference(endpoint).entity_id == arc.entity_id
    legacy = app.draft_cross_relations((saved,), draft, ((circle.entity_id, arc.entity_id),))[0]
    connected = app.draft_cross_relations((saved,), draft, ((circle.entity_id, endpoint),))[0]
    assert connected.second_endpoint == "end" and legacy.second_endpoint is None
    assert connected.relation_id == legacy.relation_id
    line = LineEntity(uuid4().hex, (0, 2), (4, 2))
    line_owner = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    connected = app.draft_cross_relations(
        (line_owner,),
        draft,
        (
            (
                DraftConnectedEndpoint(SketchGeometryReference(line.entity_id, "geometry"), "end"),
                DraftConnectedEndpoint(SketchGeometryReference(arc.entity_id, "geometry"), "start"),
            ),
        ),
    )[0]
    assert connected.first_endpoint == "end" and connected.second_endpoint == "start"


def test_fillet_contact_selects_matching_arc_endpoint() -> None:
    from mycad.core.cross_sketch_tangency import arc_tangent_endpoint, curve_endpoint_at_fillet

    arc = ArcEntity(uuid4().hex, (4, 0), 2, 90, 90)
    circle = CircleEntity(uuid4().hex, (0, 0), 2)
    line = LineEntity(uuid4().hex, (0, 2), (8, 2))
    assert arc_tangent_endpoint(arc, circle) == "end"
    assert arc_tangent_endpoint(arc, line) == "start"
    assert curve_endpoint_at_fillet(line, arc) is None
    assert curve_endpoint_at_fillet(LineEntity(uuid4().hex, (0, 2), (4, 2)), arc) == "end"
    assert curve_endpoint_at_fillet(circle, arc) is None
    with pytest.raises(ValueError):
        arc_tangent_endpoint(arc, CircleEntity(uuid4().hex, (30, 0), 2))


def test_endpoint_tangency_can_anchor_a_line_segment_to_fillet_arc() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )
    from mycad.core.sketch import PolylineEntity

    line = PolylineEntity(uuid4().hex, ((-10, 0), (0, 0)))
    arc = ArcEntity(uuid4().hex, (0, 2), 2, -90, 90)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id, 0),
        CrossSketchRef(second.sketch_id, arc.entity_id),
        "line_left",
        first_endpoint="end",
        second_endpoint="start",
    )
    validate_tangency_component((first, second), (relation,), first.sketch_id)
    with pytest.raises(ValueError, match="端点"):
        validate_tangency_component(
            (first, second), (replace(relation, first_endpoint="start"),), first.sketch_id
        )


@pytest.mark.parametrize("reverse_path", [False, True])
def test_committed_tangency_rebinds_unique_containing_arc_only_when_enabled(
    reverse_path: bool,
) -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        rebind_committed_tangencies,
    )
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import PolylineEntity

    points = ((0, 0), (10, 0), (10, 10))
    bulges = (0.2, 0.0)
    if reverse_path:
        points = tuple(reversed(points))
        bulges = tuple(-value for value in reversed(bulges))
    source = PolylineEntity(uuid4().hex, points, bulges=bulges)
    updated, _ = polyline_segment_fillet(
        source, 0, 1, 0, first_pick=points[0], second_pick=points[-1]
    )
    circle = CircleEntity(uuid4().hex, (5, -3), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 1 if reverse_path else 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "external",
    )
    before = (first, second)
    after = (replace(first, entities=(updated,)), second)
    with pytest.raises(ValueError, match="唯一重绑定"):
        rebind_committed_tangencies(before, after, (relation,), allow_extended_segments=True)
    rebound = rebind_committed_tangencies(
        before, after, (relation,), allow_extended_segments=True, allow_extended_arcs=True
    )
    assert rebound == (replace(relation, first=replace(relation.first, segment_index=1)),)


@pytest.mark.parametrize("branch", ["external", "first_contains_second", "second_contains_first"])
def test_trimmed_arc_tangency_requires_one_retained_contact(branch: str) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        TangencyBranch,
        rebind_committed_tangencies,
        rebind_committed_tangencies_for_edit,
        unique_retained_tangent_polyline_arc,
        validate_tangency_component,
    )
    from mycad.core.polyline_curves import polyline_arc_segment
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (9.12, -0.04)), bulges=(0.6, 0))
    arc = polyline_arc_segment(source, 0)

    def arc_point(ratio: float) -> tuple[float, float]:
        angle = math.radians(arc.start_angle_deg + ratio * arc.sweep_angle_deg)
        return (
            arc.center_mm[0] + arc.radius_mm * math.cos(angle),
            arc.center_mm[1] + arc.radius_mm * math.sin(angle),
        )

    line_start = source.points_mm[-1]
    updated, _ = polyline_segment_fillet(
        source, 0, 1, 0, first_pick=arc_point(0.05), second_pick=line_start
    )

    def tangent_circle(point: tuple[float, float]) -> CircleEntity:
        target_radius = arc.radius_mm + 2 if branch == "second_contains_first" else 1.0
        distance = (
            arc.radius_mm + target_radius if branch == "external" else arc.radius_mm - target_radius
        )
        scale = distance / arc.radius_mm
        center = tuple(c + (p - c) * scale for c, p in zip(arc.center_mm, point, strict=True))
        return CircleEntity(uuid4().hex, (center[0], center[1]), target_radius)

    other = tangent_circle(arc_point(0.1))
    assert unique_retained_tangent_polyline_arc(source, updated, 0, other) == 0
    assert (
        unique_retained_tangent_polyline_arc(source, updated, 0, tangent_circle(arc_point(0.01)))
        is None
    )
    assert (
        unique_retained_tangent_polyline_arc(
            source, updated, 0, tangent_circle(updated.points_mm[1])
        )
        is None
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, other.entity_id),
        cast("TangencyBranch", branch),
    )
    before = (first, second)
    after = (replace(first, entities=(updated,)), second)
    with pytest.raises(ValueError):
        rebind_committed_tangencies(before, after, (relation,), allow_extended_arcs=True)
    rebound, minimum = rebind_committed_tangencies_for_edit(before, after, (relation,))
    assert rebound == (relation,) and minimum == 37
    validate_tangency_component(after, rebound, first.sketch_id)
    wrong_branch = "first_contains_second" if branch == "external" else "external"
    with pytest.raises(ValueError, match="分支"):
        validate_tangency_component(
            after, (replace(relation, branch=wrong_branch),), first.sketch_id
        )
    changed_other = replace(second, entities=(replace(other, center_mm=(100, 100)),))
    with pytest.raises(ValueError):
        rebind_committed_tangencies_for_edit(before, (after[0], changed_other), (relation,))


@pytest.mark.parametrize("reverse_relation", [False, True])
@pytest.mark.parametrize("reflected", [False, True])
def test_trimmed_arc_tangency_rebinds_across_rotated_coplanar_frames(
    reverse_relation: bool, reflected: bool
) -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        project_tangent_entity,
        rebind_committed_tangencies_for_edit,
        validate_tangency_component,
    )
    from mycad.core.polyline_curves import polyline_arc_segment
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (9.12, -0.04)), bulges=(0.6, 0))
    arc = polyline_arc_segment(source, 0)

    def point(ratio: float) -> tuple[float, float]:
        angle = math.radians(arc.start_angle_deg + ratio * arc.sweep_angle_deg)
        return (
            arc.center_mm[0] + arc.radius_mm * math.cos(angle),
            arc.center_mm[1] + arc.radius_mm * math.sin(angle),
        )

    closed, _ = polyline_segment_fillet(
        source, 0, 1, 0, first_pick=point(0.05), second_pick=source.points_mm[-1]
    )
    contact = point(0.1)
    scale = (arc.radius_mm + 1) / arc.radius_mm
    center = tuple(c + (p - c) * scale for c, p in zip(arc.center_mm, contact, strict=True))
    circle = CircleEntity(uuid4().hex, (center[0], center[1]), 1)
    target = (
        WorkPlaneFrame((10, 5, 0), (0, 1, 0), (1, 0, 0), (0, 0, -1))
        if reflected
        else WorkPlaneFrame((10, 5, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    projected = project_tangent_entity(circle, WorkPlaneFrame.xy(), target)
    assert isinstance(projected, CircleEntity)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, target, (projected,))
    refs = (
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, projected.entity_id),
    )
    if reverse_relation:
        refs = (refs[1], refs[0])
    relation = CrossSketchTangency(uuid4().hex, *refs, "external")
    before, after = (first, second), (replace(first, entities=(closed,)), second)
    validate_tangency_component(before, (relation,), first.sketch_id)
    rebound, version = rebind_committed_tangencies_for_edit(before, after, (relation,))
    assert rebound == (relation,) and version == 37
    validate_tangency_component(after, rebound, first.sketch_id)


def test_containing_arc_rejects_partial_reversed_shifted_or_duplicate_segments() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import unique_containing_polyline_arc
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(0.2, 0))
    closed, _ = polyline_segment_fillet(source, 0, 1, 0, first_pick=(0, 0), second_pick=(10, 10))
    a, b = closed.points_mm[1:]
    bulge = closed.bulges[1]
    containing = replace(source, points_mm=(a, b), bulges=(bulge,))
    assert unique_containing_polyline_arc(source, containing, 0) == 0
    partial = replace(source, points_mm=closed.points_mm[:2], bulges=(closed.bulges[0],))
    assert unique_containing_polyline_arc(source, partial, 0) is None
    reversed_arc = replace(containing, points_mm=(b, a), bulges=(-bulge,))
    assert unique_containing_polyline_arc(source, reversed_arc, 0) is None
    shifted = replace(containing, points_mm=((a[0] + 1, a[1]), (b[0] + 1, b[1])))
    assert unique_containing_polyline_arc(source, shifted, 0) is None
    repeated = replace(containing, points_mm=(a, b, a, b), bulges=(bulge, -bulge, bulge))
    assert unique_containing_polyline_arc(source, repeated, 0) is None


def test_trimmed_polyline_line_retains_only_unique_tangent_contact() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        rebind_committed_tangencies_for_edit,
    )
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, -5), (0, 0), (10, 0), (10, 10)))
    revised = PolylineEntity(source.entity_id, ((0, -5), (0, 0), (8, 0)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 1),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    before = (first, second)
    after = (replace(first, entities=(revised,)), second)
    rebound, version = rebind_committed_tangencies_for_edit(before, after, (relation,))
    assert rebound == (relation,) and version == 40
    shifted = replace(revised, points_mm=((0, 0), (8, 0)))
    shifted_rebound, shifted_version = rebind_committed_tangencies_for_edit(
        before, (replace(first, entities=(shifted,)), second), (relation,)
    )
    assert shifted_rebound == (replace(relation, first=replace(relation.first, segment_index=0)),)
    assert shifted_version == 40
    duplicate = replace(revised, points_mm=((0, 0), (8, 0), (0, 0), (8, 0), (8, 1)))
    with pytest.raises(ValueError):
        rebind_committed_tangencies_for_edit(
            before, (replace(first, entities=(duplicate,)), second), (relation,)
        )
    lost = replace(revised, points_mm=((0, -5), (0, 0), (4, 0)))
    with pytest.raises(ValueError):
        rebind_committed_tangencies_for_edit(
            before, (replace(first, entities=(lost,)), second), (relation,)
        )
    moved = replace(second, entities=(replace(circle, center_mm=(5, 3)),))
    with pytest.raises(ValueError):
        rebind_committed_tangencies_for_edit(before, (after[0], moved), (relation,))


def test_trimmed_tangency_follows_unique_new_polyline_fragment() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        rebind_committed_tangencies_for_edit,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_edit import trim_curve_at

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    cutter = LineEntity(uuid4().hex, (2, -2), (2, 2))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, cutter))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    result = trim_curve_at(
        (*first.entities, circle), (3.5, 0), hit_tolerance_mm=0.1, target_entity_id=source.entity_id
    )
    revised = replace(
        first, entities=tuple(item for item in result if item.entity_id != circle.entity_id)
    )
    rebound, version = rebind_committed_tangencies_for_edit(
        (first, second), (revised, second), (relation,)
    )
    assert version == 43
    assert rebound[0].first.entity_id != source.entity_id
    assert rebound[0].first.segment_index == 0


def test_tangency_moves_to_new_fragment_when_segment_count_is_unchanged() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        rebind_committed_tangencies_for_edit,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_edit import trim_curve_at

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    cutter = LineEntity(uuid4().hex, (2, -2), (2, 2))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, cutter))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    result = trim_curve_at(
        (*first.entities, circle), (3.5, 0), hit_tolerance_mm=0.1, target_entity_id=source.entity_id
    )
    revised = replace(
        first, entities=tuple(item for item in result if item.entity_id != circle.entity_id)
    )
    rebound, version = rebind_committed_tangencies_for_edit(
        (first, second), (revised, second), (relation,)
    )
    assert version == 43
    assert rebound[0].first.entity_id != source.entity_id


def test_committed_tangency_rebinds_unique_extended_line_only_when_enabled() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        rebind_committed_tangencies,
    )
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(0.2, 0))
    updated, _ = polyline_segment_fillet(source, 0, 1, 0, first_pick=(0, 0), second_pick=(10, 10))
    circle = CircleEntity(uuid4().hex, (12, 5), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 1),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right",
    )
    before = (first, second)
    after = (replace(first, entities=(updated,)), second)
    with pytest.raises(ValueError, match="唯一重绑定"):
        rebind_committed_tangencies(before, after, (relation,))
    rebound = rebind_committed_tangencies(before, after, (relation,), allow_extended_segments=True)
    assert rebound == (replace(relation, first=replace(relation.first, segment_index=2)),)


@pytest.mark.parametrize(
    "points,expected",
    [
        (((-2, 0), (12, 0)), 0),
        (((12, 0), (-2, 0)), None),
        (((0, 0), (9, 0)), None),
        (((-2, 0.01), (12, 0.01)), None),
        (((-2, 0), (12, 0), (-2, 0), (12, 0)), None),
    ],
)
def test_extended_line_identity_requires_unique_directed_containment(
    points: tuple[tuple[float, float], ...], expected: int | None
) -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import unique_extended_polyline_segment
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0)))
    assert (
        unique_extended_polyline_segment(source, replace(source, points_mm=points), 0) == expected
    )


def test_committed_tangency_rebinds_closed_polyline_rotated_start() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        rebind_committed_tangencies,
    )
    from mycad.core.sketch import PolylineEntity

    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    circle = CircleEntity(uuid4().hex, (5, 5), 5)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, polyline.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    rotated = replace(polyline, points_mm=(*polyline.points_mm[1:], polyline.points_mm[0]))
    result = rebind_committed_tangencies(
        (first, second), (replace(first, entities=(rotated,)), second), (relation,)
    )
    assert result == (replace(relation, first=replace(relation.first, segment_index=3)),)


@pytest.mark.parametrize("offset", [1, 2, 3])
def test_closed_polyline_rotation_tracks_curved_bulges(offset: int) -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import closed_polyline_rotation_index
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(
        uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True, bulges=(0.3, 0, -0.2, 0)
    )
    rotated = replace(
        source,
        points_mm=(*source.points_mm[offset:], *source.points_mm[:offset]),
        bulges=(*source.bulges[offset:], *source.bulges[:offset]),
    )
    for index in range(4):
        assert closed_polyline_rotation_index(source, rotated, index) == (index - offset) % 4
    altered = replace(rotated, bulges=tuple(value + 0.01 for value in rotated.bulges))
    assert closed_polyline_rotation_index(source, altered, 0) is None


def test_rotated_closed_vertices_rebind_unchanged_segment_when_other_bulge_changes() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        rebind_committed_tangencies,
    )
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(
        uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True, bulges=(0, 0, 0.2, 0)
    )
    circle = CircleEntity(uuid4().hex, (5, 5), 5)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    changed = replace(
        source, points_mm=(*source.points_mm[1:], source.points_mm[0]), bulges=(0, 0.3, 0, 0)
    )
    result = rebind_committed_tangencies(
        (first, second), (replace(first, entities=(changed,)), second), (relation,)
    )
    assert result == (replace(relation, first=replace(relation.first, segment_index=3)),)


def test_rotated_closed_vertices_reject_changed_referenced_arc() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        rebind_committed_tangencies,
    )
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(
        uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True, bulges=(0, 0, 0.2, 0)
    )
    circle = CircleEntity(uuid4().hex, (5, 5), 5)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 2),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "external",
    )
    changed = replace(
        source, points_mm=(*source.points_mm[1:], source.points_mm[0]), bulges=(0, 0.3, 0, 0)
    )
    with pytest.raises(ValueError, match="唯一重绑定"):
        rebind_committed_tangencies(
            (first, second), (replace(first, entities=(changed,)), second), (relation,)
        )


def test_rectangle_tangent_segment_geometry_and_rebinding() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        rebind_committed_tangencies,
        tangent_entity_curve,
    )
    from mycad.core.sketch import RectangleEntity

    rectangle = RectangleEntity(uuid4().hex, (10, 20), (-2, -4))
    corners = ((10, 20), (-2, 20), (-2, -4), (10, -4))
    for index in range(4):
        segment = tangent_entity_curve(rectangle, index)
        assert isinstance(segment, LineEntity)
        assert (segment.start_mm, segment.end_mm) == (corners[index], corners[(index + 1) % 4])
    for index in (None, -1, 4):
        with pytest.raises(ValueError):
            tangent_entity_curve(rectangle, index)
    circle = CircleEntity(uuid4().hex, (0, 22), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, rectangle.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    moved = replace(rectangle, first_corner_mm=(11, 20), opposite_corner_mm=(-1, -4))
    assert rebind_committed_tangencies(
        (first, second), (replace(first, entities=(moved,)), second), (relation,)
    ) == (relation,)
    reordered = replace(rectangle, first_corner_mm=(-2, -4), opposite_corner_mm=(10, 20))
    with pytest.raises(ValueError, match="矩形边"):
        rebind_committed_tangencies(
            (first, second), (replace(first, entities=(reordered,)), second), (relation,)
        )


@pytest.mark.parametrize("angle", [0, 45, 90, 180, 270])
@pytest.mark.parametrize("reversed_corners", [False, True])
def test_rectangle_transformed_segment_mapping_rotation(angle: int, reversed_corners: bool) -> None:
    import math

    from mycad.core.cross_sketch_tangency import map_transformed_rectangle_segments
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_edit import rotate_entities

    corners = ((-3.0, -2.0), (7.0, 4.0))
    if reversed_corners:
        corners = tuple(reversed(corners))
    rectangle = RectangleEntity(uuid4().hex, corners[0], corners[1])
    result = rotate_entities((rectangle,), (rectangle.entity_id,), (0, 0), angle)[0]
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    mapping = map_transformed_rectangle_segments(
        rectangle, result, lambda p: (cosine * p[0] - sine * p[1], sine * p[0] + cosine * p[1])
    )
    assert len(mapping) == 4
    assert {index for index, _reversed in mapping} == set(range(4))
    if angle == 45:
        assert mapping == tuple((index, False) for index in range(4))


@pytest.mark.parametrize("axis", [((0, 0), (1, 0)), ((0, 0), (0, 1)), ((0, 0), (1, 1))])
def test_rectangle_transformed_segment_mapping_mirror(
    axis: tuple[tuple[int, int], tuple[int, int]],
) -> None:
    from mycad.core.cross_sketch_tangency import map_transformed_rectangle_segments
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_edit import mirror_entities

    rectangle = RectangleEntity(uuid4().hex, (7, 4), (-3, -2))
    result = mirror_entities((rectangle,), (rectangle.entity_id,), *axis)[0]
    dx, dy = axis[1]
    denominator = dx * dx + dy * dy
    mapping = map_transformed_rectangle_segments(
        rectangle,
        result,
        lambda p: (
            2 * (p[0] * dx + p[1] * dy) * dx / denominator - p[0],
            2 * (p[0] * dx + p[1] * dy) * dy / denominator - p[1],
        ),
    )
    assert {index for index, _reversed in mapping} == set(range(4))
    assert all(direction for _index, direction in mapping)


def test_rectangle_transformed_segment_mapping_rejects_inconsistent_outline() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import map_transformed_rectangle_segments
    from mycad.core.sketch import RectangleEntity

    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 5))
    with pytest.raises(ValueError, match="矩形"):
        map_transformed_rectangle_segments(
            rectangle, replace(rectangle, opposite_corner_mm=(10, 6)), lambda point: point
        )


@pytest.mark.parametrize("rectangle_first", [False, True])
@pytest.mark.parametrize("edge_reversed", [False, True])
@pytest.mark.parametrize("reflected", [False, True])
@pytest.mark.parametrize("endpoint", [None, "start", "end"])
def test_rectangle_tangency_transform_rebinds_branch_and_endpoint(
    rectangle_first: bool,
    edge_reversed: bool,
    reflected: bool,
    endpoint: Literal["start", "end"] | None,
) -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        rebind_transformed_rectangle_tangency,
    )

    rectangle = CrossSketchRef(uuid4().hex, uuid4().hex, 0)
    circle = CrossSketchRef(uuid4().hex, uuid4().hex)
    relation = CrossSketchTangency(
        uuid4().hex,
        rectangle if rectangle_first else circle,
        circle if rectangle_first else rectangle,
        "line_left",
        first_endpoint=endpoint if rectangle_first else None,
        second_endpoint=None if rectangle_first else endpoint,
    )
    updated = rebind_transformed_rectangle_tangency(
        relation, rectangle, ((2, edge_reversed), (3, False), (0, False), (1, False)), reflected
    )
    new_rectangle = updated.first if rectangle_first else updated.second
    new_endpoint = updated.first_endpoint if rectangle_first else updated.second_endpoint
    assert new_rectangle == CrossSketchRef(rectangle.sketch_id, rectangle.entity_id, 2)
    assert updated.branch == ("line_right" if reflected != edge_reversed else "line_left")
    assert new_endpoint == (
        {"start": "end", "end": "start"}[endpoint] if edge_reversed and endpoint else endpoint
    )
    assert updated.relation_id == relation.relation_id


def test_rectangle_tangency_transform_rejects_unrelated_or_invalid_branch() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        rebind_transformed_rectangle_tangency,
    )

    rectangle = CrossSketchRef(uuid4().hex, uuid4().hex, 0)
    circle = CrossSketchRef(uuid4().hex, uuid4().hex)
    relation = CrossSketchTangency(uuid4().hex, rectangle, circle, "line_left")
    mapping = tuple((index, False) for index in range(4))
    with pytest.raises(ValueError):
        rebind_transformed_rectangle_tangency(relation, circle, mapping, False)
    with pytest.raises(ValueError):
        rebind_transformed_rectangle_tangency(
            replace(relation, branch="external"), rectangle, mapping, False
        )


@pytest.mark.parametrize("reflected", [False, True])
@pytest.mark.parametrize("rectangle_first", [False, True])
def test_rectangle_tangency_rebind_matches_transformed_geometry(
    reflected: bool, rectangle_first: bool
) -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        infer_tangency_branch,
        map_transformed_rectangle_segments,
        rebind_transformed_rectangle_tangency,
        tangent_entity_curve,
    )
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_edit import mirror_entities, rotate_entities

    rectangle = RectangleEntity(uuid4().hex, (-3, 0), (7, -4))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    rectangle_ref = CrossSketchRef(uuid4().hex, rectangle.entity_id, 0)
    circle_ref = CrossSketchRef(uuid4().hex, circle.entity_id)
    old_edge = tangent_entity_curve(rectangle, 0)
    branch = infer_tangency_branch(old_edge, circle)
    relation = CrossSketchTangency(
        uuid4().hex,
        rectangle_ref if rectangle_first else circle_ref,
        circle_ref if rectangle_first else rectangle_ref,
        branch,
    )
    entities = (rectangle, circle)
    ids = (rectangle.entity_id, circle.entity_id)
    if reflected:
        changed = mirror_entities(entities, ids, (0, 0), (1, 0))
    else:
        changed = rotate_entities(entities, ids, (0, 0), 90)

    def transform(point: tuple[float, float]) -> tuple[float, float]:
        return (point[0], -point[1]) if reflected else (-point[1], point[0])

    new_rectangle, new_circle = changed
    assert isinstance(new_circle, CircleEntity)
    mapping = map_transformed_rectangle_segments(rectangle, new_rectangle, transform)
    updated = rebind_transformed_rectangle_tangency(relation, rectangle_ref, mapping, reflected)
    new_ref = updated.first if rectangle_first else updated.second
    new_edge = tangent_entity_curve(new_rectangle, new_ref.segment_index)
    assert updated.branch == infer_tangency_branch(new_edge, new_circle)


@pytest.mark.parametrize(
    "matrix,reflected",
    [((0, -1, 1, 0, 3, 5), False), ((-1, 0, 0, 1, 2, -3), True)],
)
def test_rectangle_transform_evidence_roundtrip_and_geometry(
    matrix: tuple[float, float, float, float, float, float], reflected: bool
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, RectangleTransformEvidence
    from mycad.core.sketch import RectangleEntity

    rectangle = RectangleEntity(uuid4().hex, (-3, -2), (7, 4))
    reference = CrossSketchRef(uuid4().hex, rectangle.entity_id)
    evidence = RectangleTransformEvidence(reference, matrix)
    assert RectangleTransformEvidence.from_mapping(evidence.to_mapping()) == evidence
    assert evidence.reflected is reflected
    point = evidence.apply((1, 2))
    assert point == pytest.approx(
        (matrix[0] + 2 * matrix[1] + matrix[4], matrix[2] + 2 * matrix[3] + matrix[5])
    )


@pytest.mark.parametrize(
    "matrix",
    [
        (2, 0, 0, 1, 0, 0),
        (1, 0.2, 0, 1, 0, 0),
        (1, 0, 0, 1, float("nan"), 0),
        (1, 0, 0, 1, float("inf"), 0),
    ],
)
def test_rectangle_transform_evidence_rejects_nonrigid_or_nonfinite(
    matrix: tuple[float, float, float, float, float, float],
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, RectangleTransformEvidence

    with pytest.raises(ValueError):
        RectangleTransformEvidence(CrossSketchRef(uuid4().hex, uuid4().hex), matrix)


def test_rectangle_transform_evidence_rejects_bad_mapping() -> None:
    from mycad.core.cross_sketch_tangency import RectangleTransformEvidence

    with pytest.raises(ValueError):
        RectangleTransformEvidence.from_mapping({"reference": {}, "matrix": [1, 0, 0, 1, 0, 0]})
    with pytest.raises(ValueError):
        RectangleTransformEvidence.from_mapping(
            {"reference": {"sketch_id": uuid4().hex, "entity_id": uuid4().hex}, "matrix": [1, 0]}
        )


def test_rebind_committed_tangencies_uses_verified_rectangle_transform() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        RectangleTransformEvidence,
        infer_tangency_branch,
        rebind_committed_tangencies,
        tangent_entity_curve,
    )
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_edit import rotate_entities

    rectangle = RectangleEntity(uuid4().hex, (-3, 0), (7, -4))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    reference = CrossSketchRef(first.sketch_id, rectangle.entity_id, 0)
    relation = CrossSketchTangency(
        uuid4().hex,
        reference,
        CrossSketchRef(second.sketch_id, circle.entity_id),
        infer_tangency_branch(tangent_entity_curve(rectangle, 0), circle),
    )
    changed_rectangle, changed_circle = rotate_entities(
        (rectangle, circle), (rectangle.entity_id, circle.entity_id), (0, 0), 90
    )
    updated = (
        replace(first, entities=(changed_rectangle,)),
        replace(second, entities=(changed_circle,)),
    )
    evidence = RectangleTransformEvidence(
        CrossSketchRef(first.sketch_id, rectangle.entity_id), (0, -1, 1, 0, 0, 0)
    )
    rebound = rebind_committed_tangencies((first, second), updated, (relation,), (evidence,))[0]
    assert isinstance(changed_circle, CircleEntity)
    assert rebound.branch == infer_tangency_branch(
        tangent_entity_curve(changed_rectangle, rebound.first.segment_index), changed_circle
    )
    with pytest.raises(ValueError, match="矩形"):
        rebind_committed_tangencies(
            (first, second), updated, (relation,), (replace(evidence, matrix=(1, 0, 0, 1, 0, 0)),)
        )


def test_rectangle_transform_evidence_requires_new_revision_schema() -> None:
    from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
    from mycad.commands.validation import validate_params
    from mycad.core.cross_sketch_tangency import CrossSketchRef, RectangleTransformEvidence
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch import RectangleEntity

    rectangle = RectangleEntity(uuid4().hex, (-3, 0), (7, -4))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    state = sketch.to_state_mapping()
    evidence = RectangleTransformEvidence(
        CrossSketchRef(sketch.sketch_id, rectangle.entity_id), (0, -1, 1, 0, 0, 0)
    )
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "rectangle_transforms": [evidence.to_mapping()],
    }
    old = next(
        s for s in BUILTIN_COMMAND_SPECS if s.id == "drawing.sketch.revise" and s.version == 27
    )
    new = next(
        s for s in BUILTIN_COMMAND_SPECS if s.id == "drawing.sketch.revise" and s.version == 28
    )
    with pytest.raises(ValidationError):
        validate_params(old, params, defs=COMMAND_SCHEMA_DEFS)
    assert validate_params(new, params, defs=COMMAND_SCHEMA_DEFS) == params


def test_rectangle_transform_kind_change_preserves_local_reference_semantics() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        RectangleTransformEvidence,
        rectangle_transform_kind_change_allowed,
    )
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_edit import rotate_entities

    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 5))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    result = rotate_entities((rectangle,), (rectangle.entity_id,), (0, 0), 45)[0]
    angle = math.radians(45)
    cosine, sine = math.cos(angle), math.sin(angle)
    evidence = RectangleTransformEvidence(
        CrossSketchRef(sketch.sketch_id, rectangle.entity_id), (cosine, -sine, sine, cosine, 0, 0)
    )
    assert rectangle_transform_kind_change_allowed(sketch, rectangle, result, evidence)
    assert not rectangle_transform_kind_change_allowed(sketch, rectangle, result, None)
    length = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(rectangle.entity_id, "segment", 0),),
        10,
        "mm",
    )
    assert rectangle_transform_kind_change_allowed(
        replace(sketch, constraints=(length,)), rectangle, result, evidence
    )
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(rectangle.entity_id, "end"),)
    )
    assert not rectangle_transform_kind_change_allowed(
        replace(sketch, constraints=(constraint,)), rectangle, result, evidence
    )
    with pytest.raises(ValueError, match="矩形"):
        rectangle_transform_kind_change_allowed(
            sketch, rectangle, result, replace(evidence, matrix=(1, 0, 0, 1, 0, 0))
        )


def test_rectangle_rotation_does_not_silently_rebind_equal_length_dimension() -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        RectangleTransformEvidence,
        rectangle_transform_local_references_preserved,
    )
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_edit import rotate_entities

    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    length = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(rectangle.entity_id, "segment", 0),),
        10,
        "mm",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,), (length,))
    rotated = rotate_entities((rectangle,), (rectangle.entity_id,), (0, 0), 90)[0]
    evidence = RectangleTransformEvidence(
        CrossSketchRef(sketch.sketch_id, rectangle.entity_id), (0, -1, 1, 0, 0, 0)
    )
    assert not rectangle_transform_local_references_preserved(sketch, rectangle, rotated, evidence)


def test_rectangle_transform_rebinds_local_segments_and_vertices() -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        RectangleTransformEvidence,
        map_transformed_rectangle_segments,
        rebind_rectangle_local_constraints,
    )
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_edit import rotate_entities

    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    segment = SketchGeometryReference(rectangle.entity_id, "segment", 0)
    end = SketchGeometryReference(rectangle.entity_id, "end")
    length = SketchConstraint(uuid4().hex, "length", (segment,), 10, "mm")
    diagonal = SketchConstraint(
        uuid4().hex,
        "distance",
        (SketchGeometryReference(rectangle.entity_id, "start"), end),
        math.sqrt(200),
        "mm",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,), (length, diagonal))
    changed = rotate_entities((rectangle,), (rectangle.entity_id,), (0, 0), 90)[0]
    evidence = RectangleTransformEvidence(
        CrossSketchRef(sketch.sketch_id, rectangle.entity_id), (0, -1, 1, 0, 0, 0)
    )
    mapping = map_transformed_rectangle_segments(rectangle, changed, evidence.apply)
    rebound_length, rebound_diagonal = rebind_rectangle_local_constraints(sketch, changed, evidence)
    assert rebound_length.references[0] == SketchGeometryReference(
        rectangle.entity_id, "segment", mapping[0][0]
    )
    end_index, reverse = mapping[2]
    assert rebound_diagonal.references[1] == SketchGeometryReference(
        rectangle.entity_id, "vertex", (end_index + int(reverse)) % 4
    )
    assert (
        rebound_length.value == length.value
        and rebound_diagonal.constraint_id == diagonal.constraint_id
    )


def test_rectangle_reflection_rebinds_tangent_endpoint_and_dimension_anchor() -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        RectangleTransformEvidence,
        map_transformed_rectangle_segments,
        rebind_rectangle_local_constraints,
    )
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_edit import mirror_entities

    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 5))
    arc = ArcEntity(uuid4().hex, (5, 2), 2, 0, 90)
    segment = SketchGeometryReference(rectangle.entity_id, "segment", 0)
    tangent = SketchConstraint(
        uuid4().hex,
        "tangent",
        (segment, SketchGeometryReference(arc.entity_id, "geometry")),
        first_endpoint="start",
        second_endpoint="end",
    )
    length = SketchConstraint(uuid4().hex, "length", (segment,), 10, "mm", anchor_mode="start")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle, arc), (tangent, length))
    changed = mirror_entities((rectangle,), (rectangle.entity_id,), (0, 0), (1, 0))[0]
    evidence = RectangleTransformEvidence(
        CrossSketchRef(sketch.sketch_id, rectangle.entity_id), (1, 0, 0, -1, 0, 0)
    )
    mapping = map_transformed_rectangle_segments(rectangle, changed, evidence.apply)
    assert mapping[0][1]
    updated_tangent, updated_length = rebind_rectangle_local_constraints(sketch, changed, evidence)
    assert updated_tangent.first_endpoint == "end" and updated_tangent.second_endpoint == "end"
    assert updated_length.anchor_mode == "end"
    assert updated_tangent.references[0].index == mapping[0][0]


def test_rectangle_and_polyline_transform_share_one_branch_flip() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        RectangleTransformEvidence,
        rebind_committed_tangencies,
    )
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.core.sketch_edit import mirror_entities

    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, -5))
    polyline = PolylineEntity(uuid4().hex, ((2, 0), (6, 0)), bulges=(0.5,))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, rectangle.entity_id, 0),
        CrossSketchRef(second.sketch_id, polyline.entity_id, 0),
        "line_left",
    )
    mirrored_rectangle = mirror_entities((rectangle,), (rectangle.entity_id,), (0, 0), (0, 1))[0]
    mirrored_polyline = mirror_entities((polyline,), (polyline.entity_id,), (0, 0), (0, 1))[0]
    before = (first, second)
    after = (
        replace(first, entities=(mirrored_rectangle,)),
        replace(second, entities=(mirrored_polyline,)),
    )
    matrix = (-1, 0, 0, 1, 0, 0)
    rect_proof = RectangleTransformEvidence(
        CrossSketchRef(first.sketch_id, rectangle.entity_id), matrix
    )
    poly_proof = RectangleTransformEvidence(
        CrossSketchRef(second.sketch_id, polyline.entity_id), matrix
    )
    expected = rebind_committed_tangencies(before, after, (relation,), (rect_proof,))
    assert (
        rebind_committed_tangencies(before, after, (relation,), (rect_proof,), (poly_proof,))
        == expected
    )
    other_polyline = mirror_entities((polyline,), (polyline.entity_id,), (0, 0), (1, 0))[0]
    mismatch = (after[0], replace(second, entities=(other_polyline,)))
    other_proof = replace(poly_proof, matrix=(1, 0, 0, -1, 0, 0))
    with pytest.raises(ValueError, match="变换依据不一致"):
        rebind_committed_tangencies(before, mismatch, (relation,), (rect_proof,), (other_proof,))


def test_split_retained_transform_evidence_rejects_duplicates_and_unknowns() -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        RectangleTransformEvidence,
        split_transform_evidence,
    )
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0)))
    line = LineEntity(uuid4().hex, (0, 0), (0, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle, polyline, line))
    proofs = tuple(
        RectangleTransformEvidence(
            CrossSketchRef(sketch.sketch_id, entity.entity_id), (1, 0, 0, 1, 0, 0)
        )
        for entity in (rectangle, polyline, line)
    )
    assert split_transform_evidence((sketch,), proofs) == ((proofs[0],), (proofs[1],), (proofs[2],))
    with pytest.raises(ValueError, match="重复"):
        split_transform_evidence((sketch,), (proofs[0], proofs[0]))
    with pytest.raises(ValueError, match="不支持"):
        split_transform_evidence((), (proofs[0],))
