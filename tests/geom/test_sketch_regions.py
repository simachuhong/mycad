# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Region identities are independent of geometry and contour iteration order."""

from dataclasses import replace
from math import pi
from pathlib import Path

import pytest

from mycad.app import (
    build_app,
    commit_new_sketch,
    create_replay_candidate,
    new_document,
    open_app_document,
    separate_internal_sketch,
)
from mycad.core.exceptions import GeometryBuildError
from mycad.core.persistence import document_payload, save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import (
    CircleEntity,
    LineEntity,
    PointEntity,
    RectangleEntity,
    Sketch,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.geom.sketch_profiles import make_sketch_regions, select_sketch_region


def test_regions_keep_outer_identity_and_holes_when_entities_are_reordered() -> None:
    outer = CircleEntity("a1" * 16, (0, 0), 10)
    hole = CircleEntity("b2" * 16, (0, 0), 3)
    island = CircleEntity("c3" * 16, (30, 0), 4)
    construction = CircleEntity("d4" * 16, (60, 0), 5, construction=True)
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (outer, hole, island, construction))
    regions = make_sketch_regions(sketch)
    reordered = make_sketch_regions(replace(sketch, entities=tuple(reversed(sketch.entities))))
    by_id = {region.boundary_entity_ids: region for region in regions}
    assert set(by_id) == {(outer.entity_id,), (island.entity_id,)}
    assert {region.boundary_entity_ids for region in reordered} == set(by_id)
    ring = by_id[(outer.entity_id,)]
    assert ring.hole_entity_ids == ((hole.entity_id,),)
    assert ring.face.is_inside((5, 0, 0))
    assert not ring.face.is_inside((0, 0, 0))
    assert by_id[(island.entity_id,)].hole_entity_ids == ()


def test_open_region_is_rejected_by_the_same_validation_as_features() -> None:
    line = LineEntity("a1" * 16, (0, 0), (10, 0))
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (line,))
    with pytest.raises(GeometryBuildError, match="开口|闭合|闭环"):
        make_sketch_regions(sketch)


def test_select_region_uses_boundary_identity_and_rejects_missing_reference() -> None:
    outer = CircleEntity("a1" * 16, (0, 0), 10)
    island = CircleEntity("b2" * 16, (30, 0), 4)
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (outer, island))
    selected = select_sketch_region(sketch, (island.entity_id,))
    assert selected.face.area == pytest.approx(16 * 3.141592653589793)
    resized = replace(sketch, entities=(outer, replace(island, radius_mm=6)))
    assert select_sketch_region(resized, (island.entity_id,)).face.area == pytest.approx(
        36 * 3.141592653589793
    )
    with pytest.raises(GeometryBuildError, match="区域.*失效"):
        select_sketch_region(replace(sketch, entities=(outer,)), (island.entity_id,))


def test_region_display_mesh_comes_from_the_same_face_and_preserves_hole() -> None:
    outer = CircleEntity("a1" * 16, (0, 0), 10)
    hole = CircleEntity("b2" * 16, (0, 0), 3)
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (outer, hole))
    services = build_app(discoverers=())
    region = services.kernel.sketch_region_data(sketch)[0]
    assert region.boundary_entity_ids == (outer.entity_id,)
    assert region.mesh.triangle_indices
    for triangle in region.mesh.triangle_indices:
        vertices = [region.mesh.vertices[index] for index in triangle]
        center_x = sum(vertex[0] for vertex in vertices) / 3
        center_y = sum(vertex[1] for vertex in vertices) / 3
        assert center_x**2 + center_y**2 > 8.5
    assert not services.kernel.sketches


def test_selected_region_extrusion_replays_and_preserves_old_all_regions_behavior(
    tmp_path: Path,
) -> None:
    outer = CircleEntity("a1" * 16, (0, 0), 10)
    hole = CircleEntity("b2" * 16, (0, 0), 3)
    island = CircleEntity("c3" * 16, (30, 0), 4)
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (outer, hole, island))
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    params = {
        "profile": {
            "type": "sketch",
            "sketch_id": sketch.sketch_id,
            "boundary_entity_ids": [outer.entity_id],
        },
        "distance": 5,
    }
    loaded.bus.execute("feature.extrude", params, version=5, confirmed_by="local")
    assert services.kernel.mass_properties().volume == pytest.approx(455 * pi)
    path = tmp_path / "region.mc.json"
    save_document(loaded.document, path)
    reopened = open_app_document(services, path)
    assert services.kernel.mass_properties().volume == pytest.approx(455 * pi)
    reopened.bus.undo()
    assert services.kernel.mass_properties().volume == 0
    reopened.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(455 * pi)
    reopened.bus.undo()
    reopened.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": sketch.sketch_id}, "distance": 5},
        version=4,
        confirmed_by="local",
    )
    assert services.kernel.mass_properties().volume == pytest.approx(535 * pi)


def test_selected_region_revolves_without_other_regions() -> None:
    selected = RectangleEntity("a1" * 16, (2, 0), (4, 5))
    other = RectangleEntity("b2" * 16, (8, 0), (10, 5))
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (selected, other))
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    loaded.bus.execute(
        "feature.revolve",
        {
            "profile": {
                "type": "sketch",
                "sketch_id": sketch.sketch_id,
                "boundary_entity_ids": [selected.entity_id],
            },
            "axis": "Y",
        },
        version=4,
        confirmed_by="local",
    )
    assert services.kernel.mass_properties().volume == pytest.approx(60 * pi)


def test_missing_selected_region_fails_without_committing() -> None:
    circle = CircleEntity("a1" * 16, (0, 0), 10)
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (circle,))
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute("sketch.create", sketch.to_mapping())
    before = document_payload(loaded.document)
    with pytest.raises(GeometryBuildError, match="区域.*失效"):
        loaded.bus.execute(
            "feature.extrude",
            {
                "profile": {
                    "type": "sketch",
                    "sketch_id": sketch.sketch_id,
                    "boundary_entity_ids": ["b2" * 16],
                },
                "distance": 5,
            },
            version=5,
        )
    assert document_payload(loaded.document) == before
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.mass_properties().volume == 0


def test_point_sketch_replays_and_points_do_not_form_profile_edges(tmp_path: Path) -> None:
    circle = CircleEntity("a1" * 16, (0, 0), 10)
    point = PointEntity("b2" * 16, (2, 3))
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (circle, point))
    services = build_app(discoverers=())
    loaded = new_document(services)
    candidate = create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("sketch.create", 5, sketch.to_mapping(version=4), "local"),),
            False,
            target_archive_version=6,
        ),
        current_session_identity=1,
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.sketch_display_data()[0].points[0].entity_id == point.entity_id
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": sketch.sketch_id}, "distance": 5},
    )
    assert services.kernel.mass_properties().volume == pytest.approx(500 * pi)
    path = tmp_path / "point.mc.json"
    save_document(loaded.document, path)
    open_app_document(services, path)
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.mass_properties().volume == pytest.approx(500 * pi)


def test_point_can_participate_in_a_distance_constraint() -> None:
    first = PointEntity("a1" * 16, (0, 0))
    second = PointEntity("b2" * 16, (3, 4))
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (first, second))
    distance = SketchConstraint(
        "c3" * 16,
        "distance",
        (
            SketchGeometryReference(first.entity_id, "vertex", 0),
            SketchGeometryReference(second.entity_id, "vertex", 0),
        ),
        10,
        "mm",
    )
    services = build_app(discoverers=())
    result = services.kernel.preview_sketch_constraint(sketch, distance)
    assert result.status == "success", result.message
    assert result.sketch is not None
    moved_first, moved_second = result.sketch.entities
    assert isinstance(moved_first, PointEntity) and isinstance(moved_second, PointEntity)
    assert moved_first.position_mm != moved_second.position_mm
    assert sum(
        (a - b) ** 2 for a, b in zip(moved_first.position_mm, moved_second.position_mm, strict=True)
    ) == pytest.approx(100)


def test_point_sketch_can_be_detached_with_a_replayable_archive() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    point = PointEntity("a1" * 16, (2, 3))
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (point,))
    commit_new_sketch(services, loaded, sketch, session_identity=1)
    isolated, detached = separate_internal_sketch(services, sketch.sketch_id)
    assert detached.document.archive_version == 6
    assert isolated.kernel.sketches[0].entities == (point,)


def test_selected_region_extrusion_rebuilds_after_driving_dimension_edit() -> None:
    outer = CircleEntity("a1" * 16, (0, 0), 10)
    other = CircleEntity("b2" * 16, (30, 0), 4)
    radius = SketchConstraint(
        "c3" * 16, "radius", (SketchGeometryReference(outer.entity_id, "geometry"),), 10, "mm"
    )
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (outer, other), (radius,))
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), version=3)
    loaded.bus.execute(
        "feature.extrude",
        {
            "profile": {
                "type": "sketch",
                "sketch_id": sketch.sketch_id,
                "boundary_entity_ids": [outer.entity_id],
            },
            "distance": 5,
        },
        version=5,
    )
    changed = replace(radius, value=12)
    result = services.kernel.preview_sketch_constraint_update(sketch, changed)
    assert result.status == "success"
    loaded.bus.execute(
        "sketch.constraint.update", result.command_params(sketch, changed), version=1
    )
    assert services.kernel.mass_properties().volume == pytest.approx(720 * pi)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(500 * pi)
