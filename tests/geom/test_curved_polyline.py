# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact geometry for a polyline containing circular segments."""

import math
from pathlib import Path
from uuid import uuid4

import pytest

from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments
from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
from mycad.geom.sketch_profiles import make_sketch_faces


@pytest.mark.parametrize("distance, radius", ((1, 4), (-1, 6)))
def test_offset_curved_polyline_builds_exact_closed_profile(distance: float, radius: float) -> None:
    from mycad.core.sketch_edit import offset_entities

    source = PolylineEntity(
        uuid4().hex, ((-5, 0), (5, 0), (5, 10), (-5, 10)), True, bulges=(0, 1, 0, 1)
    )
    result = offset_entities((source,), (source.entity_id,), distance)[1]
    assert isinstance(result, PolylineEntity)
    faces = make_sketch_faces(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (result,)))
    assert len(faces) == 1 and faces[0].is_valid
    assert faces[0].area == pytest.approx(20 * radius + math.pi * radius**2)


def test_offset_curved_polyline_regenerates_extrusion_and_reopens(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
    from mycad.core.sketch_edit import offset_entities

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services)
    source = PolylineEntity(
        uuid4().hex, ((-5, 0), (5, 0), (5, 10), (-5, 10)), True, bulges=(0, 1, 0, 1)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=17)
    loaded.bus.execute(
        "feature.extrude",
        {
            "profile": {"type": "sketch", "sketch_id": sketch.sketch_id},
            "distance": 5,
            "mode": "new",
        },
        "local",
        version=2,
    )
    offset = offset_entities((source,), (source.entity_id,), 1)[1]
    assert isinstance(offset, PolylineEntity)
    from dataclasses import replace

    offset = replace(offset, entity_id=source.entity_id)
    state = Sketch(sketch.sketch_id, sketch.frame, (offset,)).to_state_mapping()
    revision = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    candidate = app.create_replay_candidate(services, loaded, session_identity=17)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("drawing.sketch.revise", 3, {"revisions": [revision]}, "local"),),
            False,
            6,
        ),
        current_session_identity=17,
    )
    preview = candidate.preview(current_session_identity=17)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=17), current_session_identity=17
    )
    volume = (80 + 16 * math.pi) * 5
    assert services.kernel.mass_properties().volume == pytest.approx(volume)
    path = tmp_path / "offset-profile.mc.json"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx((100 + 25 * math.pi) * 5)
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(volume)
    app.open_app_document(services, path)
    assert services.kernel.mass_properties().volume == pytest.approx(volume)


@pytest.mark.parametrize("reverse", [False, True])
def test_curved_polyline_profile_uses_exact_circular_edges(reverse: bool) -> None:
    points = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    source = PolylineEntity(uuid4().hex, tuple(reversed(points)) if reverse else points, True)
    vertices, bulges = polyline_fillet_trimmed_segments(source, 2.0)
    rounded = PolylineEntity(source.entity_id, vertices, True, bulges=bulges)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rounded,))
    faces = make_sketch_faces(sketch)
    assert len(faces) == 1
    assert faces[0].area == pytest.approx(100.0 - (4.0 - math.pi) * 4.0)
    assert faces[0].outer_wire().length == pytest.approx(24.0 + 4.0 * math.pi)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("radius", [0.0, 1.0])
def test_closed_polyline_refillet_keeps_exact_area(reverse: bool, radius: float) -> None:
    points = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    source = PolylineEntity(uuid4().hex, tuple(reversed(points)) if reverse else points, True)
    vertices, bulges = polyline_fillet_trimmed_segments(source, 2.0)
    rounded = PolylineEntity(source.entity_id, vertices, True, bulges=bulges)
    new_vertices, new_bulges = polyline_fillet_trimmed_segments(rounded, radius)
    result = PolylineEntity(source.entity_id, new_vertices, True, bulges=new_bulges)
    faces = make_sketch_faces(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (result,)))
    assert faces[0].area == pytest.approx(100 - (4 - math.pi) * radius**2)


@pytest.mark.parametrize("reverse", [False, True])
def test_closed_mixed_polyline_fillet_creates_valid_exact_profile(reverse: bool) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import ArcEntity

    points = ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0), (0.0, 5.0))
    quarter = 2**0.5 - 1
    # Reverse a closed path while keeping each directed arc on the same edge.
    if reverse:
        points = tuple(reversed(points))
        bulges = (0, -quarter, 0, 0)
    else:
        bulges = (0, quarter, 0, 0)
    source = PolylineEntity(uuid4().hex, points, True, bulges=bulges)
    vertices, result_bulges = polyline_fillet_trimmed_segments(source, 1)
    result = PolylineEntity(source.entity_id, vertices, True, bulges=result_bulges)
    segments = polyline_curve_segments(result.points_mm, result.bulges, True, result.entity_id)
    assert sum(isinstance(segment, ArcEntity) for segment in segments) >= 3
    faces = make_sketch_faces(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (result,)))
    assert len(faces) == 1 and faces[0].is_valid and faces[0].area > 0


def test_curved_polyline_viewport_and_snaps_follow_arc() -> None:
    from mycad.geom.kernel import BuildKernel

    entity = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=(1, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    kernel = BuildKernel()
    kernel.apply("sketch.create", sketch.to_state_mapping())
    curve = kernel.sketch_display_data()[0].curves[0]
    assert min(point[1] for point in curve.points) == pytest.approx(-1.0)
    anchors = kernel.snap_anchor_data()
    assert any(
        anchor.kind == "midpoint" and anchor.point == pytest.approx((1, -1, 0))
        for anchor in anchors
    )


def test_curved_polyline_new_sketch_roundtrips_archive(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    entity = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=(1, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=17)
    assert loaded.document.commands[-1].version == 8
    path = tmp_path / "curved.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    loaded.bus.redo()
    reopened_services = app.build_app(discoverers=[])
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.undo()
    assert not reopened_services.kernel.sketches


def test_curved_polyline_revision_preserves_identity_and_replays(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=17)
    vertices, bulges = polyline_fillet_trimmed_segments(source, 2)
    rounded = PolylineEntity(source.entity_id, vertices, True, bulges=bulges)
    revised = Sketch(sketch.sketch_id, sketch.frame, (rounded,))
    state = revised.to_state_mapping()
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ]
    }
    # Upgrade the archive through the same isolated candidate path as the UI.
    candidate = app.create_replay_candidate(services, loaded, session_identity=17)
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet

    candidate.stage(
        ReplayChangeSet((), (ReplayAppend("drawing.sketch.revise", 3, params, "local"),), False, 6),
        current_session_identity=17,
    )
    assert candidate.preview(current_session_identity=17).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=17), current_session_identity=17
    )
    assert services.kernel.sketches == (revised,)
    path = tmp_path / "revision.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)
    loaded.bus.redo()
    assert services.kernel.sketches == (revised,)
    reopened_services = app.build_app(discoverers=[])
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (revised,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)


def test_constraint_solver_does_not_flatten_curved_polyline() -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.geom.sketch_constraints import solve_sketch_constraint

    entity = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=(1, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    constraint = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(entity.entity_id, "segment", 0),)
    )
    result = solve_sketch_constraint(sketch, constraint)
    assert result.status == "invalid"
    assert result.message is not None and "圆弧" in result.message
    assert sketch.entities == (entity,)


def test_curved_polyline_arc_is_not_measured_as_a_straight_segment() -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.geom.sketch_constraints import measure_sketch_dimension

    entity = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=(1, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(entity.entity_id, "segment", 0),), 2, "mm"
    )
    with pytest.raises(ValueError, match="圆弧段"):
        measure_sketch_dimension(sketch, dimension)


def test_curved_polyline_revision_regenerates_dependent_extrusion(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(), "local")
    loaded.bus.execute(
        "feature.extrude",
        {
            "profile": {"type": "sketch", "sketch_id": sketch.sketch_id},
            "distance": 5,
            "mode": "new",
        },
        "local",
        version=2,
    )
    vertices, bulges = polyline_fillet_trimmed_segments(source, 2)
    rounded = PolylineEntity(source.entity_id, vertices, True, bulges=bulges)
    state = Sketch(sketch.sketch_id, sketch.frame, (rounded,)).to_state_mapping()
    revision = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    candidate = app.create_replay_candidate(services, loaded, session_identity=17)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("drawing.sketch.revise", 3, {"revisions": [revision]}, "local"),),
            False,
            6,
        ),
        current_session_identity=17,
    )
    preview = candidate.preview(current_session_identity=17)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=17), current_session_identity=17
    )
    volume = (100 - (4 - math.pi) * 4) * 5
    assert services.kernel.mass_properties().volume == pytest.approx(volume)
    path = tmp_path / "curved-profile.mc.json"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(500)
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(volume)
    reopened = app.open_app_document(services, path)
    assert reopened.document.commands
    assert services.kernel.mass_properties().volume == pytest.approx(volume)
