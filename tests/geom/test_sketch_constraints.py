# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""PlaneGCS preview results stay disposable until accepted through the Bus."""

from __future__ import annotations

import math
from dataclasses import replace
from math import hypot
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import pytest

from mycad.app import build_app, commit_new_sketch, new_document, open_app_document
from mycad.core.exceptions import GeometryBuildError, ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
    SketchSupportFace,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import (
    ConstraintKind,
    ConstraintUnit,
    SketchConstraint,
    SketchGeometryReference,
)
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.geom import sketch_constraints as sketch_constraint_adapter
from mycad.geom.sketch_constraints import solve_sketch_constraint, solve_sketch_drag

if TYPE_CHECKING:
    from planegcs.sketch import Sketch as PlaneGcsSketch


class _EntityBindingLike(Protocol):
    entity: SketchEntity


SKETCH_ID = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
LINE_ID = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
HORIZONTAL_ID = "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c"
VERTICAL_ID = "3d3d3d3d-3d3d-4d3d-8d3d-3d3d3d3d3d3d"
LENGTH_ID = "4e4e4e4e-4e4e-4e4e-8e4e-4e4e4e4e4e4e"
OTHER_LINE_ID = "5f5f5f5f-5f5f-4f5f-8f5f-5f5f5f5f5f5f"
CIRCLE_ID = "6a6a6a6a-6a6a-4a6a-8a6a-6a6a6a6a6a6a"
OTHER_CIRCLE_ID = "7b7b7b7b-7b7b-4b7b-8b7b-7b7b7b7b7b7b"
ARC_ID = "8c8c8c8c-8c8c-4c8c-8c8c-8c8c8c8c8c8c"


def test_initial_sketch_persists_only_satisfied_inferred_tangency(tmp_path: Path) -> None:
    line = LineEntity(LINE_ID, (-5.0, 0.0), (0.0, 0.0))
    arc = ArcEntity(ARC_ID, (0.0, 2.0), 2.0, 180.0, 90.0)
    tangent = SketchConstraint(
        HORIZONTAL_ID,
        "tangent",
        (SketchGeometryReference(LINE_ID, "geometry"), SketchGeometryReference(ARC_ID, "geometry")),
        source="inferred",
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line, arc), (tangent,))
    services = build_app(discoverers=[])
    loaded = new_document(services)
    commit_new_sketch(services, loaded, sketch, session_identity=1)
    target = tmp_path / "tangent.mc.json"
    save_document(loaded.document, target)
    reopened = open_app_document(services, target)
    assert reopened.document.commands == loaded.document.commands
    bad_arc = replace(arc, center_mm=(0.0, 3.0))
    invalid = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line, bad_arc), (tangent,))
    other = new_document(services)
    with pytest.raises(ValidationError):
        commit_new_sketch(services, other, invalid, session_identity=1)


@pytest.mark.parametrize("valid", [False, True])
@pytest.mark.parametrize("curved", [False, True])
def test_initial_inferred_tangency_accepts_only_valid_polyline_segment(
    tmp_path: Path, valid: bool, curved: bool
) -> None:
    polyline = PolylineEntity(
        LINE_ID, ((0, 0), (10, 0), (10, -5)), bulges=(0, 0.5) if curved else ()
    )
    arc = ArcEntity(ARC_ID, (8, 2 if valid else 3), 2, 270, 90)
    relation = SketchConstraint(
        HORIZONTAL_ID,
        "tangent",
        (
            SketchGeometryReference(LINE_ID, "segment", 0),
            SketchGeometryReference(ARC_ID, "geometry"),
        ),
        source="inferred",
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (polyline, arc), (relation,))
    services = build_app(discoverers=[])
    loaded = new_document(services)
    if not valid:
        with pytest.raises(ValidationError):
            commit_new_sketch(services, loaded, sketch, session_identity=1)
        assert not loaded.document.commands
        return
    commit_new_sketch(services, loaded, sketch, session_identity=1)
    target = tmp_path / "inferred-segment.mc.json"
    save_document(loaded.document, target)
    reopened = open_app_document(services, target)
    assert reopened.document.commands == loaded.document.commands
    assert services.kernel.sketches[0].constraints == (relation,)


def test_initial_inferred_tangency_rejects_wrong_polyline_segment() -> None:
    polyline = PolylineEntity(LINE_ID, ((0, 0), (10, 0), (10, -5)))
    arc = ArcEntity(ARC_ID, (8, 2), 2, 270, 90)
    relation = SketchConstraint(
        HORIZONTAL_ID,
        "tangent",
        (
            SketchGeometryReference(LINE_ID, "segment", 1),
            SketchGeometryReference(ARC_ID, "geometry"),
        ),
        source="inferred",
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (polyline, arc), (relation,))
    services = build_app(discoverers=[])
    loaded = new_document(services)
    with pytest.raises(ValidationError):
        commit_new_sketch(services, loaded, sketch, session_identity=1)
    assert not loaded.document.commands


def test_fillet_inferred_tangencies_and_endpoints_survive_radius_solve() -> None:
    from mycad.core.line_fillet import line_fillet

    first = LineEntity(LINE_ID, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(OTHER_LINE_ID, (0.0, 0.0), (0.0, 10.0))
    a, b, arc = line_fillet(first, second, (8.0, 0.0), (0.0, 8.0), 2.0, ARC_ID)
    constraints = (
        SketchConstraint(
            HORIZONTAL_ID,
            "tangent",
            (
                SketchGeometryReference(LINE_ID, "geometry"),
                SketchGeometryReference(ARC_ID, "geometry"),
            ),
            source="inferred",
        ),
        SketchConstraint(
            VERTICAL_ID,
            "tangent",
            (
                SketchGeometryReference(OTHER_LINE_ID, "geometry"),
                SketchGeometryReference(ARC_ID, "geometry"),
            ),
            source="inferred",
        ),
        SketchConstraint(
            LENGTH_ID,
            "coincident",
            (SketchGeometryReference(LINE_ID, "start"), SketchGeometryReference(ARC_ID, "start")),
            source="inferred",
        ),
        SketchConstraint(
            CIRCLE_ID,
            "coincident",
            (
                SketchGeometryReference(OTHER_LINE_ID, "start"),
                SketchGeometryReference(ARC_ID, "end"),
            ),
            source="inferred",
        ),
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (a, b, arc), constraints)
    radius = SketchConstraint(
        OTHER_CIRCLE_ID,
        "radius",
        (SketchGeometryReference(ARC_ID, "geometry"),),
        value=3.0,
        unit="mm",
    )
    result = solve_sketch_constraint(sketch, radius)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    assert len(result.sketch.constraints) == 5


def _line_sketch() -> Sketch:
    return Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(LINE_ID, (2.0, 3.0), (12.0, 6.0)),),
    )


def test_successful_solve_reports_reversed_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    line = LineEntity(LINE_ID, (0.0, 0.0), (10.0, 0.0))
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (line,),
        (
            SketchConstraint(
                HORIZONTAL_ID, "horizontal", (SketchGeometryReference(LINE_ID, "geometry"),)
            ),
            SketchConstraint(VERTICAL_ID, "fixed", (SketchGeometryReference(LINE_ID, "start"),)),
        ),
    )

    def reversed_entity(_solver: PlaneGcsSketch, binding: _EntityBindingLike) -> SketchEntity:
        assert isinstance(binding.entity, LineEntity)
        return replace(binding.entity, end_mm=(-10.0, 0.0))

    monkeypatch.setattr(sketch_constraint_adapter, "_read_solved_entity", reversed_entity)
    result = solve_sketch_constraint(
        sketch, _constraint(LENGTH_ID, "length", value=10.0, unit="mm")
    )
    assert result.status == "success", result.message
    assert result.degrees_of_freedom == 0
    assert any(change.kind == "direction" for change in result.branch_changes)


def test_constrained_drag_reports_reversed_branch() -> None:
    line = LineEntity(LINE_ID, (0.0, 0.0), (10.0, 0.0))
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (line,),
        (
            SketchConstraint(VERTICAL_ID, "fixed", (SketchGeometryReference(LINE_ID, "start"),)),
            _constraint(LENGTH_ID, "length", value=10.0, unit="mm"),
        ),
    )
    result = solve_sketch_drag(sketch, SketchGeometryReference(LINE_ID, "end"), (-10.0, 0.0))
    assert result.status == "success", result.message
    assert any(change.kind == "direction" for change in result.branch_changes)


def _constraint(
    constraint_id: str,
    kind: str,
    *,
    value: float | None = None,
    unit: str | None = None,
) -> SketchConstraint:
    return SketchConstraint(
        constraint_id,
        cast("ConstraintKind", kind),
        (SketchGeometryReference(LINE_ID, "geometry"),),
        value,
        cast("ConstraintUnit | None", unit),
    )


def test_driving_length_preview_moves_line_and_returns_replay_values() -> None:
    sketch = _line_sketch()
    constraint = _constraint(LENGTH_ID, "length", value=20.0, unit="mm")

    result = solve_sketch_constraint(sketch, constraint)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")

    assert result.status == "success"
    assert result.sketch is not None
    assert result.sketch.constraints == (constraint,)
    solved = result.sketch.entities[0]
    assert isinstance(solved, LineEntity)
    assert hypot(solved.end_mm[0] - solved.start_mm[0], solved.end_mm[1] - solved.start_mm[1]) == (
        pytest.approx(20.0, abs=1e-6)
    )
    assert result.degrees_of_freedom == 3
    params = result.command_params(sketch, constraint)
    assert params["sketch_id"] == SKETCH_ID
    assert params["base_state_sha256"] == sketch.state_digest()
    assert params["solver_id"] == "planegcs"
    assert params["solver_version"]
    assert params["solution_entities"] == result.sketch.to_mapping(version=3)["entities"]
    source_line = sketch.entities[0]
    assert isinstance(source_line, LineEntity)
    assert source_line.end_mm == (12.0, 6.0)


def test_unrelated_curved_polyline_survives_line_constraint_and_drag() -> None:
    line = LineEntity(LINE_ID, (0, 0), (10, 0))
    curved = PolylineEntity(OTHER_LINE_ID, ((20, 0), (22, 0), (22, 2)), bulges=(1, 0))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line, curved))
    constraint = _constraint(LENGTH_ID, "length", value=20, unit="mm")
    result = solve_sketch_constraint(sketch, constraint)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    assert result.sketch.entities[1] == curved
    assert result.degrees_of_freedom == 10
    dragged = solve_sketch_drag(result.sketch, SketchGeometryReference(LINE_ID, "end"), (12, 16))
    assert dragged.status == "success", dragged.message
    assert dragged.sketch is not None and dragged.sketch.entities[1] == curved
    moved_line = dragged.sketch.entities[0]
    assert isinstance(moved_line, LineEntity)
    assert moved_line.end_mm == pytest.approx((12, 16))


def test_curved_polyline_constraints_and_invalid_drag_are_still_rejected() -> None:
    curved = PolylineEntity(OTHER_LINE_ID, ((20, 0), (22, 0), (22, 2)), bulges=(1, 0))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,))
    constraint = SketchConstraint(
        HORIZONTAL_ID,
        "horizontal",
        (SketchGeometryReference(OTHER_LINE_ID, "segment", 0),),
    )
    assert solve_sketch_constraint(sketch, constraint).status == "invalid"
    result = solve_sketch_drag(sketch, SketchGeometryReference(OTHER_LINE_ID, "segment", 0), (1, 1))
    assert result.status == "invalid"
    other = LineEntity(LINE_ID, (0, 0), (10, 0))
    existing = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (other, curved), (constraint,))
    assert (
        solve_sketch_constraint(
            existing, _constraint(LENGTH_ID, "length", value=20, unit="mm")
        ).status
        == "invalid"
    )
    assert (
        solve_sketch_drag(existing, SketchGeometryReference(LINE_ID, "end"), (20, 0)).status
        == "invalid"
    )


@pytest.mark.parametrize("bulge", [0.5, -0.5])
@pytest.mark.parametrize("kind", ["horizontal", "vertical", "length"])
def test_curved_polyline_straight_segment_constraints_preserve_arc_branch(
    bulge: float, kind: ConstraintKind
) -> None:
    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (3, 2), (9, 3)), bulges=(bulge, 0))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,))
    reference = SketchGeometryReference(OTHER_LINE_ID, "segment", 1)
    constraint = SketchConstraint(
        HORIZONTAL_ID,
        kind,
        (reference,),
        8 if kind == "length" else None,
        "mm" if kind == "length" else None,
    )
    result = solve_sketch_constraint(sketch, constraint)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, PolylineEntity)
    assert solved.bulges == curved.bulges
    start, end = solved.points_mm[1:]
    if kind == "horizontal":
        assert start[1] == pytest.approx(end[1])
    elif kind == "vertical":
        assert start[0] == pytest.approx(end[0])
    else:
        assert math.dist(start, end) == pytest.approx(8)


@pytest.mark.parametrize("kind", ["parallel", "perpendicular", "angle"])
@pytest.mark.parametrize("reverse", [False, True])
def test_curved_polyline_straight_segment_relates_to_line(
    kind: ConstraintKind, reverse: bool
) -> None:
    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (3, 2), (9, 3)), bulges=(0.5, 0))
    line = LineEntity(LINE_ID, (20, 0), (25, 4))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved, line))
    references = (
        SketchGeometryReference(OTHER_LINE_ID, "segment", 1),
        SketchGeometryReference(LINE_ID, "geometry"),
    )
    if reverse:
        references = references[::-1]
    constraint = SketchConstraint(
        HORIZONTAL_ID,
        kind,
        references,
        45 if kind == "angle" else None,
        "deg" if kind == "angle" else None,
    )
    result = solve_sketch_constraint(sketch, constraint)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    solved, solved_line = result.sketch.entities
    assert isinstance(solved, PolylineEntity) and solved.bulges == curved.bulges
    assert isinstance(solved_line, LineEntity)
    a = (
        solved.points_mm[2][0] - solved.points_mm[1][0],
        solved.points_mm[2][1] - solved.points_mm[1][1],
    )
    b = (
        solved_line.end_mm[0] - solved_line.start_mm[0],
        solved_line.end_mm[1] - solved_line.start_mm[1],
    )
    dot = a[0] * b[0] + a[1] * b[1]
    cross = a[0] * b[1] - a[1] * b[0]
    if kind == "parallel":
        assert cross == pytest.approx(0, abs=1e-6)
    elif kind == "perpendicular":
        assert dot == pytest.approx(0, abs=1e-6)
    else:
        assert abs(math.degrees(math.atan2(cross, dot))) == pytest.approx(45, abs=1e-5)


def test_curved_polyline_straight_constraint_replays_and_reopens(tmp_path: Path) -> None:
    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (3, 2), (9, 3)), bulges=(0.5, 0))
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,))
    commit_new_sketch(services, loaded, sketch, session_identity=1)
    current = services.kernel.sketches[0]
    constraint = SketchConstraint(
        HORIZONTAL_ID, "horizontal", (SketchGeometryReference(OTHER_LINE_ID, "segment", 1),)
    )
    result = solve_sketch_constraint(current, constraint)
    assert result.status == "success", result.message
    loaded.bus.execute(
        "sketch.constraint.add", result.command_params(current, constraint), confirmed_by="local"
    )
    after = services.kernel.sketches
    path = tmp_path / "curved-straight-constraint.my2d"
    save_document(loaded.document, path)
    reopened = open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_curved_polyline_straight_constraint_keeps_driving_arc_radius() -> None:
    from mycad.core.polyline_curves import polyline_arc_segment

    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (3, 2), (9, 3)), bulges=(0.5, 0))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,))
    radius = SketchConstraint(
        LENGTH_ID,
        "radius",
        (SketchGeometryReference(OTHER_LINE_ID, "segment", 0),),
        polyline_arc_segment(curved, 0).radius_mm,
        "mm",
    )
    first = solve_sketch_constraint(sketch, radius)
    if first.status == "unavailable":
        pytest.skip(first.message or "PlaneGCS is unavailable")
    assert first.status == "success", first.message
    assert first.sketch is not None
    horizontal = SketchConstraint(
        HORIZONTAL_ID, "horizontal", (SketchGeometryReference(OTHER_LINE_ID, "segment", 1),)
    )
    result = solve_sketch_constraint(first.sketch, horizontal)
    assert result.status == "success", result.message
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, PolylineEntity)
    assert solved.points_mm[1][1] == pytest.approx(solved.points_mm[2][1])
    assert polyline_arc_segment(solved, 0).radius_mm == pytest.approx(radius.value)


@pytest.mark.parametrize("bulge", (0.5, -0.5, 2.0, -2.0))
@pytest.mark.parametrize("kind", ("radius", "diameter", "arc_length"))
def test_curved_polyline_arc_segment_reference_measurement(bulge: float, kind: str) -> None:
    from mycad.core.polyline_curves import bulge_arc

    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (10, 0), (10, 5)), bulges=(bulge, 0))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,))
    dimension = SketchConstraint(
        LENGTH_ID,
        cast("ConstraintKind", kind),
        (SketchGeometryReference(OTHER_LINE_ID, "segment", 0),),
        None,
        "mm",
        False,
    )
    result = solve_sketch_constraint(sketch, dimension)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    arc = bulge_arc(curved.points_mm[0], curved.points_mm[1], bulge, curved.entity_id)
    expected = arc.radius_mm * (2 if kind == "diameter" else 1)
    if kind == "arc_length":
        expected = arc.radius_mm * abs(math.radians(arc.sweep_angle_deg))
    assert result.sketch.constraints[0].value == pytest.approx(expected)
    assert result.sketch.entities == (curved,)


@pytest.mark.parametrize("bulge", (0.5, -0.5, 2.0, -2.0))
def test_curved_polyline_arc_segment_driving_radius_with_fixed_endpoints(bulge: float) -> None:
    from mycad.core.polyline_curves import bulge_arc

    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (10, 0), (10, 5)), bulges=(bulge, 0))
    fixed = tuple(
        SketchConstraint(
            identity, "fixed", (SketchGeometryReference(OTHER_LINE_ID, "vertex", index),)
        )
        for index, identity in enumerate((HORIZONTAL_ID, VERTICAL_ID))
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,), fixed)
    radius = SketchConstraint(
        LENGTH_ID, "radius", (SketchGeometryReference(OTHER_LINE_ID, "segment", 0),), 7.5, "mm"
    )
    result = solve_sketch_constraint(sketch, radius)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    assert result.degrees_of_freedom == 2
    solved = result.sketch.entities[0]
    assert isinstance(solved, PolylineEntity)
    assert solved.points_mm[0] == pytest.approx(curved.points_mm[0])
    assert solved.points_mm[1] == pytest.approx(curved.points_mm[1])
    assert solved.bulges[0] * bulge > 0
    assert (abs(solved.bulges[0]) > 1) == (abs(bulge) > 1)
    assert solved.bulges[1] == 0
    arc = bulge_arc(solved.points_mm[0], solved.points_mm[1], solved.bulges[0], solved.entity_id)
    assert arc.radius_mm == pytest.approx(7.5, abs=1e-7)


@pytest.mark.parametrize("reverse", (False, True))
def test_curved_polyline_arc_segment_tangent_to_line(reverse: bool) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import bulge_arc

    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (10, 0), (10, 5)), bulges=(1, 0))
    line = LineEntity(LINE_ID, (-5, -6), (15, -6))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved, line))
    arc_ref = SketchGeometryReference(OTHER_LINE_ID, "segment", 0)
    line_ref = SketchGeometryReference(LINE_ID, "geometry")
    tangent = SketchConstraint(
        HORIZONTAL_ID, "tangent", (line_ref, arc_ref) if reverse else (arc_ref, line_ref)
    )
    result = solve_sketch_constraint(sketch, tangent)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    moved_curve, moved_line = result.sketch.entities
    assert isinstance(moved_curve, PolylineEntity) and isinstance(moved_line, LineEntity)
    arc = bulge_arc(
        moved_curve.points_mm[0],
        moved_curve.points_mm[1],
        moved_curve.bulges[0],
        moved_curve.entity_id,
    )
    assert tangent_on_curves(moved_line, arc)
    assert moved_curve.bulges[0] > 0 and moved_curve.bulges[1] == 0


@pytest.mark.parametrize("kind", ("circle", "arc"))
def test_curved_polyline_arc_segment_tangent_to_circular_curve(kind: str) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_arc_segment

    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (10, 0), (10, 5)), bulges=(1, 0))
    other = (
        CircleEntity(CIRCLE_ID, (5, -7), 2)
        if kind == "circle"
        else ArcEntity(ARC_ID, (5, -7), 2, 0, 180)
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved, other))
    relation = SketchConstraint(
        HORIZONTAL_ID,
        "tangent",
        (
            SketchGeometryReference(OTHER_LINE_ID, "segment", 0),
            SketchGeometryReference(other.entity_id, "geometry"),
        ),
    )
    result = solve_sketch_constraint(sketch, relation)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    moved, solved_other = result.sketch.entities
    assert isinstance(moved, PolylineEntity) and isinstance(solved_other, CircleEntity | ArcEntity)
    assert tangent_on_curves(polyline_arc_segment(moved, 0), solved_other)


@pytest.mark.parametrize("bulge", (0.5, -0.5))
@pytest.mark.parametrize("kind", ("diameter", "arc_length"))
def test_curved_polyline_arc_segment_driving_dimensions(bulge: float, kind: str) -> None:
    from mycad.core.polyline_curves import polyline_arc_segment

    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (10, 0), (10, 5)), bulges=(bulge, 0))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,))
    dimension = SketchConstraint(
        LENGTH_ID,
        cast("ConstraintKind", kind),
        (SketchGeometryReference(OTHER_LINE_ID, "segment", 0),),
        10.0,
        "mm",
    )
    result = solve_sketch_constraint(sketch, dimension)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    moved = result.sketch.entities[0]
    assert isinstance(moved, PolylineEntity)
    arc = polyline_arc_segment(moved, 0)
    measured = (
        2 * arc.radius_mm
        if kind == "diameter"
        else arc.radius_mm * abs(math.radians(arc.sweep_angle_deg))
    )
    assert measured == pytest.approx(10, abs=1e-7)
    assert moved.bulges[0] * bulge > 0


def test_clockwise_arc_driving_length_preserves_signed_sweep() -> None:
    arc = ArcEntity(ARC_ID, (0, 0), 5, 90, -90)
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (arc,))
    dimension = SketchConstraint(
        LENGTH_ID, "arc_length", (SketchGeometryReference(ARC_ID, "geometry"),), 10, "mm"
    )
    result = solve_sketch_constraint(sketch, dimension)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, ArcEntity)
    assert solved.sweep_angle_deg < 0
    assert solved.radius_mm * abs(math.radians(solved.sweep_angle_deg)) == pytest.approx(10)


def test_curved_polyline_arc_radius_rejects_impossible_fixed_endpoints() -> None:
    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (10, 0), (10, 5)), bulges=(0.5, 0))
    fixed = tuple(
        SketchConstraint(
            identity, "fixed", (SketchGeometryReference(OTHER_LINE_ID, "vertex", index),)
        )
        for index, identity in enumerate((HORIZONTAL_ID, VERTICAL_ID))
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,), fixed)
    radius = SketchConstraint(
        LENGTH_ID, "radius", (SketchGeometryReference(OTHER_LINE_ID, "segment", 0),), 4, "mm"
    )
    result = solve_sketch_constraint(sketch, radius)
    assert result.status in ("invalid", "failed")
    assert sketch.entities == (curved,) and sketch.constraints == fixed


def test_curved_polyline_arc_radius_replays_and_reopens(tmp_path: Path) -> None:
    from mycad.core.polyline_curves import polyline_arc_segment

    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (10, 0), (10, 5)), bulges=(0.5, 0))
    fixed = tuple(
        SketchConstraint(
            identity, "fixed", (SketchGeometryReference(OTHER_LINE_ID, "vertex", index),)
        )
        for index, identity in enumerate((HORIZONTAL_ID, VERTICAL_ID))
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,), fixed)
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    commit_new_sketch(services, loaded, sketch, session_identity=1)
    current = services.kernel.sketches[0]
    radius = SketchConstraint(
        LENGTH_ID, "radius", (SketchGeometryReference(OTHER_LINE_ID, "segment", 0),), 7.5, "mm"
    )
    result = solve_sketch_constraint(current, radius)
    assert result.status == "success", result.message
    loaded.bus.execute(
        "sketch.constraint.add", result.command_params(current, radius), confirmed_by="local"
    )
    after = services.kernel.sketches
    actual = after[0].entities[0]
    assert isinstance(actual, PolylineEntity)
    assert polyline_arc_segment(actual, 0).radius_mm == pytest.approx(7.5)
    path = tmp_path / "polyline-radius.my2d"
    save_document(loaded.document, path)
    reopened = open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("kind", ("concentric", "equal"))
def test_curved_polyline_arc_segment_circle_relation(kind: str) -> None:
    from mycad.core.polyline_curves import polyline_arc_segment

    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (10, 0), (10, 5)), bulges=(0.5, 0))
    circle = CircleEntity(CIRCLE_ID, (5, 4), 8)
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved, circle))
    relation = SketchConstraint(
        HORIZONTAL_ID,
        cast("ConstraintKind", kind),
        (
            SketchGeometryReference(OTHER_LINE_ID, "segment", 0),
            SketchGeometryReference(CIRCLE_ID, "geometry"),
        ),
    )
    result = solve_sketch_constraint(sketch, relation)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    moved, solved_circle = result.sketch.entities
    assert isinstance(moved, PolylineEntity) and isinstance(solved_circle, CircleEntity)
    arc = polyline_arc_segment(moved, 0)
    if kind == "concentric":
        assert arc.center_mm == pytest.approx(solved_circle.center_mm, abs=1e-7)
    else:
        assert arc.radius_mm == pytest.approx(solved_circle.radius_mm, abs=1e-7)


def test_curved_polyline_vertex_fixed_and_coincident_drag() -> None:
    curved = PolylineEntity(OTHER_LINE_ID, ((20, 0), (22, 0), (22, 2)), bulges=(1, 0))
    line = LineEntity(LINE_ID, (22, 0), (30, 0))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved, line))
    fixed = SketchConstraint(
        HORIZONTAL_ID, "fixed", (SketchGeometryReference(OTHER_LINE_ID, "vertex", 0),)
    )
    first = solve_sketch_constraint(sketch, fixed)
    if first.status == "unavailable":
        pytest.skip(first.message or "PlaneGCS is unavailable")
    assert first.status == "success", first.message
    assert first.sketch is not None
    assert first.degrees_of_freedom == 9
    coincident = SketchConstraint(
        VERTICAL_ID,
        "coincident",
        (
            SketchGeometryReference(OTHER_LINE_ID, "vertex", 1),
            SketchGeometryReference(LINE_ID, "start"),
        ),
    )
    result = solve_sketch_constraint(first.sketch, coincident)
    assert result.status == "success", result.message
    assert result.sketch is not None
    dragged = solve_sketch_drag(result.sketch, SketchGeometryReference(LINE_ID, "start"), (24, 1))
    assert dragged.status == "success", dragged.message
    assert dragged.sketch is not None
    moved, moved_line = dragged.sketch.entities
    assert isinstance(moved, PolylineEntity) and isinstance(moved_line, LineEntity)
    assert moved.points_mm[0] == pytest.approx((20, 0))
    assert moved.points_mm[1] == pytest.approx((24, 1))
    assert moved_line.start_mm == pytest.approx((24, 1))
    assert moved.bulges == curved.bulges
    assert (
        solve_sketch_drag(
            result.sketch, SketchGeometryReference(OTHER_LINE_ID, "vertex", 0), (19, 1)
        ).status
        == "failed"
    )


def test_curved_polyline_vertex_distance_constraint() -> None:
    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (3, 0), (3, 2)), bulges=(0.5, -0.25))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,))
    distance = SketchConstraint(
        LENGTH_ID,
        "distance",
        (
            SketchGeometryReference(OTHER_LINE_ID, "vertex", 0),
            SketchGeometryReference(OTHER_LINE_ID, "vertex", 1),
        ),
        5,
        "mm",
    )
    result = solve_sketch_constraint(sketch, distance)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    moved = result.sketch.entities[0]
    assert isinstance(moved, PolylineEntity)
    assert math.dist(moved.points_mm[0], moved.points_mm[1]) == pytest.approx(5)
    assert moved.bulges == curved.bulges


def test_curved_polyline_vertex_constraints_reject_locked_and_degenerate_edits() -> None:
    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (3, 0), (3, 2)), bulges=(0.5, 0))
    fixed = SketchConstraint(
        HORIZONTAL_ID, "fixed", (SketchGeometryReference(OTHER_LINE_ID, "vertex", 0),)
    )
    locked = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (curved,),
        layers=SketchLayerTable((SketchLayer("0", locked=True),)),
    )
    assert solve_sketch_constraint(locked, fixed).status == "invalid"
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,), (fixed,))
    result = solve_sketch_drag(sketch, SketchGeometryReference(OTHER_LINE_ID, "vertex", 1), (0, 0))
    assert result.status in ("invalid", "failed")
    assert sketch.entities == (curved,) and sketch.constraints == (fixed,)


def test_curved_polyline_vertex_reference_distance_refreshes_on_drag() -> None:
    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (3, 0), (3, 2)), bulges=(0.5, 0))
    reference = SketchConstraint(
        LENGTH_ID,
        "distance",
        (
            SketchGeometryReference(OTHER_LINE_ID, "vertex", 0),
            SketchGeometryReference(OTHER_LINE_ID, "vertex", 1),
        ),
        3,
        "mm",
        False,
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,), (reference,))
    result = solve_sketch_drag(sketch, SketchGeometryReference(OTHER_LINE_ID, "vertex", 1), (4, 0))
    assert result.status == "success", result.message
    assert result.sketch is not None
    assert result.sketch.constraints[0].value == pytest.approx(4)
    moved = result.sketch.entities[0]
    assert isinstance(moved, PolylineEntity) and moved.bulges == curved.bulges


def test_curved_polyline_vertex_constraint_replays_and_reopens(tmp_path: Path) -> None:
    curved = PolylineEntity(OTHER_LINE_ID, ((0, 0), (3, 0), (3, 2)), bulges=(0.5, -0.25))
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,))
    commit_new_sketch(services, loaded, sketch, session_identity=1)
    current = services.kernel.sketches[0]
    distance = SketchConstraint(
        LENGTH_ID,
        "distance",
        (
            SketchGeometryReference(OTHER_LINE_ID, "vertex", 0),
            SketchGeometryReference(OTHER_LINE_ID, "vertex", 1),
        ),
        5,
        "mm",
    )
    result = solve_sketch_constraint(current, distance)
    assert result.status == "success", result.message
    loaded.bus.execute(
        "sketch.constraint.add", result.command_params(current, distance), confirmed_by="local"
    )
    after = services.kernel.sketches
    assert after[0].constraints == (distance,)
    path = tmp_path / "curved-vertex.my2d"
    save_document(loaded.document, path)
    reopened = open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_unconstrained_curved_polyline_vertex_drag_preserves_bulges_and_other_constraints() -> None:
    line = LineEntity(LINE_ID, (0, 0), (10, 0))
    curved = PolylineEntity(OTHER_LINE_ID, ((20, 0), (22, 0), (22, 2)), bulges=(1, 0))
    fixed = SketchConstraint(HORIZONTAL_ID, "fixed", (SketchGeometryReference(LINE_ID, "start"),))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line, curved), (fixed,))
    result = solve_sketch_drag(sketch, SketchGeometryReference(OTHER_LINE_ID, "vertex", 1), (24, 1))
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    moved = result.sketch.entities[1]
    assert isinstance(moved, PolylineEntity)
    assert moved.points_mm == ((20, 0), (24, 1), (22, 2))
    assert moved.bulges == curved.bulges
    assert result.sketch.entities[0] == line
    assert result.sketch.constraints == (fixed,)
    assert sketch.entities == (line, curved)


def test_curved_polyline_vertex_drag_rejects_degenerate_target_and_locked_layer() -> None:
    layers = SketchLayerTable().add(SketchLayer("curve", locked=True))
    curved = PolylineEntity(
        OTHER_LINE_ID, ((20, 0), (22, 0), (22, 2)), layer_name="curve", bulges=(1, 0)
    )
    locked = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (curved,), layers=layers)
    ref = SketchGeometryReference(OTHER_LINE_ID, "vertex", 1)
    assert solve_sketch_drag(locked, ref, (24, 1)).status == "invalid"
    unlocked = replace(locked, layers=SketchLayerTable().add(SketchLayer("curve")))
    result = solve_sketch_drag(unlocked, ref, (20, 0))
    assert result.status in ("invalid", "failed")
    assert unlocked.entities == (curved,)


@pytest.mark.parametrize("curve_locked", [False, True])
def test_reference_dimension_with_unrelated_curved_polyline(curve_locked: bool) -> None:
    layers = SketchLayerTable().add(SketchLayer("curves", locked=curve_locked))
    line = LineEntity(LINE_ID, (0, 0), (10, 0))
    curved = PolylineEntity(
        OTHER_LINE_ID, ((20, 0), (22, 0), (22, 2)), layer_name="curves", bulges=(1, 0)
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line, curved), layers=layers)
    constraint = SketchConstraint(
        LENGTH_ID, "length", (SketchGeometryReference(LINE_ID, "geometry"),), 10, "mm", False
    )
    result = solve_sketch_constraint(sketch, constraint)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None and result.sketch.entities == sketch.entities
    assert result.degrees_of_freedom == (4 if curve_locked else 11)


def test_unrelated_curved_polyline_constraint_replays_and_reopens(tmp_path: Path) -> None:
    line = LineEntity(LINE_ID, (0, 0), (10, 0))
    curved = PolylineEntity(OTHER_LINE_ID, ((20, 0), (22, 0), (22, 2)), bulges=(1, 0))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line, curved))
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    commit_new_sketch(services, loaded, sketch, session_identity=1)
    current = services.kernel.sketches[0]
    constraint = _constraint(LENGTH_ID, "length", value=20, unit="mm")
    result = solve_sketch_constraint(current, constraint)
    assert result.status == "success", result.message
    loaded.bus.execute(
        "sketch.constraint.add", result.command_params(current, constraint), confirmed_by="local"
    )
    assert services.kernel.sketches[0].entities[1] == curved
    path = tmp_path / "curved-unrelated-constraint.mc.json"
    save_document(loaded.document, path)
    reopened = open_app_document(services, path)
    assert services.kernel.sketches[0].entities[1] == curved
    reopened.bus.undo()
    assert services.kernel.sketches[0].entities == (line, curved)
    reopened.bus.redo()
    assert services.kernel.sketches[0].entities[1] == curved
    assert services.kernel.sketches[0].constraints == (constraint,)


def test_constrained_endpoint_drag_preserves_fixed_anchor_and_length() -> None:
    line = LineEntity(LINE_ID, (0.0, 0.0), (20.0, 0.0))
    fixed_id = "8d8d8d8d-8d8d-4d8d-8d8d-8d8d8d8d8d8d"
    length_id = "9e9e9e9e-9e9e-4e9e-8e9e-9e9e9e9e9e9e"
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (line,),
        (
            SketchConstraint(
                fixed_id,
                "fixed",
                (SketchGeometryReference(LINE_ID, "start"),),
            ),
            SketchConstraint(
                length_id,
                "length",
                (SketchGeometryReference(LINE_ID, "geometry"),),
                20.0,
                "mm",
            ),
        ),
    )

    result = solve_sketch_drag(
        sketch,
        SketchGeometryReference(LINE_ID, "end"),
        (0.0, 20.0),
    )
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")

    assert result.status == "success"
    assert result.sketch is not None
    assert result.sketch.constraints == sketch.constraints
    solved = result.sketch.entities[0]
    assert isinstance(solved, LineEntity)
    assert solved.start_mm == pytest.approx((0.0, 0.0), abs=1e-6)
    assert solved.end_mm == pytest.approx((0.0, 20.0), abs=1e-6)


def test_constrained_endpoint_drag_refuses_to_move_a_fixed_control_point() -> None:
    fixed_id = "8d8d8d8d-8d8d-4d8d-8d8d-8d8d8d8d8d8d"
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(LINE_ID, (0.0, 0.0), (20.0, 0.0)),),
        (
            SketchConstraint(
                fixed_id,
                "fixed",
                (SketchGeometryReference(LINE_ID, "start"),),
            ),
        ),
    )

    result = solve_sketch_drag(sketch, SketchGeometryReference(LINE_ID, "start"), (2.0, 3.0))

    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "failed"
    assert result.sketch is None
    assert result.conflicting_constraint_ids == (fixed_id,)
    original_line = sketch.entities[0]
    assert isinstance(original_line, LineEntity)
    assert original_line.start_mm == (0.0, 0.0)


def test_constrained_endpoint_drag_projects_pixel_rounded_target_onto_feasible_geometry() -> None:
    line = LineEntity(LINE_ID, (0.0, 0.0), (20.0, 0.0))
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (line,),
        (
            SketchConstraint(
                "8d8d8d8d-8d8d-4d8d-8d8d-8d8d8d8d8d8d",
                "fixed",
                (SketchGeometryReference(LINE_ID, "start"),),
            ),
            SketchConstraint(
                "9e9e9e9e-9e9e-4e9e-8e9e-9e9e9e9e9e9e",
                "length",
                (SketchGeometryReference(LINE_ID, "geometry"),),
                20.0,
                "mm",
            ),
        ),
    )

    result = solve_sketch_drag(
        sketch,
        SketchGeometryReference(LINE_ID, "end"),
        (-0.1, 20.0),
    )
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")

    assert result.status == "success"
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, LineEntity)
    assert solved.start_mm == pytest.approx((0.0, 0.0), abs=1e-6)
    assert hypot(solved.end_mm[0], solved.end_mm[1]) == pytest.approx(20.0, abs=1e-6)


def test_driving_constraint_solution_preserves_entity_layer_and_layer_table() -> None:
    layer = SketchLayer("OUTLINE", color_rgb=(10, 80, 150), linetype="DASHED")
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(LINE_ID, (2.0, 3.0), (12.0, 6.0), layer_name="OUTLINE"),),
        layers=SketchLayerTable().add(layer),
    )

    result = solve_sketch_constraint(
        sketch, _constraint(LENGTH_ID, "length", value=20.0, unit="mm")
    )

    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success"
    assert result.sketch is not None
    assert result.sketch.entities[0].layer_name == "OUTLINE"
    assert result.sketch.layers == sketch.layers


def test_conflicting_preview_identifies_constraints_and_keeps_input_unchanged() -> None:
    sketch = _line_sketch()
    horizontal = _constraint(HORIZONTAL_ID, "horizontal")
    first = solve_sketch_constraint(sketch, horizontal)
    if first.status == "unavailable":
        pytest.skip(first.message or "PlaneGCS is unavailable")
    assert first.status == "success"
    assert first.sketch is not None
    before = first.sketch

    result = solve_sketch_constraint(before, _constraint(VERTICAL_ID, "vertical"))

    assert result.status == "failed"
    assert result.sketch is None
    assert set(result.conflicting_constraint_ids) == {HORIZONTAL_ID, VERTICAL_ID}
    assert before.constraints == (horizontal,)
    assert before.entities == first.sketch.entities


def test_solver_success_is_rejected_when_horizontal_relation_residual_is_large(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def corrupt_solved_entity(_solver: PlaneGcsSketch, binding: _EntityBindingLike) -> SketchEntity:
        entity = binding.entity
        assert isinstance(entity, LineEntity)
        return LineEntity(
            entity.entity_id,
            entity.start_mm,
            (entity.end_mm[0], entity.end_mm[1] + 2.0),
            entity.construction,
        )

    monkeypatch.setattr(sketch_constraint_adapter, "_read_solved_entity", corrupt_solved_entity)
    result = solve_sketch_constraint(_line_sketch(), _constraint(HORIZONTAL_ID, "horizontal"))
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")

    assert result.status == "failed"
    assert result.sketch is None
    assert result.conflicting_constraint_ids == (HORIZONTAL_ID,)
    assert "残差" in (result.message or "")


@pytest.mark.parametrize(
    ("entities", "reference_ids"),
    (
        (
            (
                LineEntity(LINE_ID, (-10.0, 0.0), (10.0, 0.0)),
                CircleEntity(CIRCLE_ID, (0.0, 8.0), 5.0),
            ),
            (LINE_ID, CIRCLE_ID),
        ),
        (
            (
                LineEntity(LINE_ID, (-10.0, 0.0), (10.0, 0.0)),
                ArcEntity(ARC_ID, (0.0, 0.0), 5.0, 0.0, 359.0),
            ),
            (LINE_ID, ARC_ID),
        ),
        (
            (
                CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0),
                CircleEntity(OTHER_CIRCLE_ID, (14.0, 0.0), 3.0),
            ),
            (CIRCLE_ID, OTHER_CIRCLE_ID),
        ),
        (
            (
                CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0),
                ArcEntity(ARC_ID, (14.0, 0.0), 3.0, 180.0, 359.0),
            ),
            (CIRCLE_ID, ARC_ID),
        ),
        (
            (
                ArcEntity(ARC_ID, (0.0, 0.0), 5.0, 30.0, 359.0),
                ArcEntity(OTHER_CIRCLE_ID, (14.0, 0.0), 3.0, 210.0, 359.0),
            ),
            (ARC_ID, OTHER_CIRCLE_ID),
        ),
    ),
    ids=("line-circle", "line-arc", "circle-circle", "circle-arc", "arc-arc"),
)
def test_tangent_relation_solves_with_independent_contact_validation(
    entities: tuple[LineEntity | CircleEntity | ArcEntity, ...],
    reference_ids: tuple[str, str],
) -> None:
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), entities)
    constraint = SketchConstraint(
        HORIZONTAL_ID,
        "tangent",
        tuple(SketchGeometryReference(identity, "geometry") for identity in reference_ids),
    )

    result = solve_sketch_constraint(sketch, constraint)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")

    assert result.status == "success", result.message
    assert result.sketch is not None
    assert result.sketch.constraints[-1] == constraint


def test_arc_tangency_outside_swept_section_is_rejected() -> None:
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (
            LineEntity(LINE_ID, (-10.0, 0.0), (10.0, 0.0)),
            ArcEntity(ARC_ID, (0.0, 0.0), 5.0, 0.0, 90.0),
        ),
    )
    constraint = SketchConstraint(
        HORIZONTAL_ID,
        "tangent",
        (
            SketchGeometryReference(LINE_ID, "geometry"),
            SketchGeometryReference(ARC_ID, "geometry"),
        ),
    )

    result = solve_sketch_constraint(sketch, constraint)

    assert result.status == "failed"
    assert result.sketch is None
    assert result.conflicting_constraint_ids == (HORIZONTAL_ID,)
    assert "关系残差" in (result.message or "")


def test_redundant_constraint_is_reported_by_stable_id() -> None:
    sketch = _line_sketch()
    first_constraint = _constraint(HORIZONTAL_ID, "horizontal")
    first = solve_sketch_constraint(sketch, first_constraint)
    if first.status == "unavailable":
        pytest.skip(first.message or "PlaneGCS is unavailable")
    assert first.status == "success", first.message
    assert first.sketch is not None
    duplicate = _constraint(VERTICAL_ID, "horizontal")

    result = solve_sketch_constraint(first.sketch, duplicate)

    assert result.status == "success", result.message
    assert VERTICAL_ID in result.redundant_constraint_ids


def test_rectangle_segment_dimension_preserves_connected_right_angle_profile() -> None:
    rectangle = RectangleEntity(LINE_ID, (0.0, 0.0), (20.0, 10.0))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (rectangle,))
    constraint = SketchConstraint(
        LENGTH_ID,
        "length",
        (SketchGeometryReference(LINE_ID, "segment", 0),),
        30.0,
        "mm",
    )

    result = solve_sketch_constraint(sketch, constraint)

    assert result.status == "success"
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, RectangleEntity)
    assert abs(solved.opposite_corner_mm[0] - solved.first_corner_mm[0]) == pytest.approx(30.0)
    assert abs(solved.opposite_corner_mm[1] - solved.first_corner_mm[1]) == pytest.approx(10.0)


@pytest.mark.parametrize(
    ("kind", "value", "unit"),
    (
        ("horizontal", None, None),
        ("vertical", None, None),
        ("fixed", None, None),
        ("length", 20.0, "mm"),
    ),
)
def test_line_constraints_solve_for_supported_relations(
    kind: str, value: float | None, unit: str | None
) -> None:
    sketch = _line_sketch()
    reference = (
        SketchGeometryReference(LINE_ID, "start")
        if kind == "fixed"
        else SketchGeometryReference(LINE_ID, "geometry")
    )
    constraint = SketchConstraint(
        LENGTH_ID,
        cast("ConstraintKind", kind),
        (reference,),
        value,
        cast("ConstraintUnit | None", unit),
    )

    result = solve_sketch_constraint(sketch, constraint)

    assert result.status == "success", result.message
    assert result.sketch is not None
    assert result.degrees_of_freedom is not None
    if kind == "fixed":
        solved_line = result.sketch.entities[0]
        assert isinstance(solved_line, LineEntity)
        assert solved_line.start_mm == pytest.approx((2.0, 3.0), abs=1e-9)


@pytest.mark.parametrize("extent_mm", (0.01, 1.0, 1000.0, 100000.0))
def test_horizontal_relation_solves_across_calibrated_sketch_scales(extent_mm: float) -> None:
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(LINE_ID, (0.0, 2.0 * extent_mm), (extent_mm, 2.4 * extent_mm)),),
    )

    result = solve_sketch_constraint(sketch, _constraint(HORIZONTAL_ID, "horizontal"))
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")

    assert result.status == "success", result.message
    assert result.sketch is not None
    solved_line = result.sketch.entities[0]
    assert isinstance(solved_line, LineEntity)
    dx = solved_line.end_mm[0] - solved_line.start_mm[0]
    dy = solved_line.end_mm[1] - solved_line.start_mm[1]
    assert math.degrees(abs(math.atan2(dy, dx))) == pytest.approx(0.0, abs=1e-7)


def test_reference_length_does_not_move_geometry() -> None:
    sketch = _line_sketch()
    constraint = SketchConstraint(
        LENGTH_ID,
        "length",
        (SketchGeometryReference(LINE_ID, "geometry"),),
        None,
        "mm",
        driving=False,
    )

    result = solve_sketch_constraint(sketch, constraint)

    assert result.status == "success", result.message
    assert result.sketch is not None
    assert result.sketch.entities == sketch.entities
    measured = result.sketch.constraints[0]
    assert measured.value == pytest.approx(hypot(10.0, 3.0), abs=1e-9)


def test_two_geometry_relations_and_circle_dimensions_solve() -> None:
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (
            LineEntity(LINE_ID, (0.0, 0.0), (10.0, 2.0)),
            LineEntity(OTHER_LINE_ID, (20.0, 0.0), (28.0, 6.0)),
        ),
    )
    parallel = SketchConstraint(
        LENGTH_ID,
        "parallel",
        (
            SketchGeometryReference(LINE_ID, "geometry"),
            SketchGeometryReference(OTHER_LINE_ID, "geometry"),
        ),
    )
    parallel_result = solve_sketch_constraint(sketch, parallel)
    assert parallel_result.status == "success", parallel_result.message

    perpendicular = SketchConstraint(
        OTHER_CIRCLE_ID,
        "perpendicular",
        (
            SketchGeometryReference(LINE_ID, "geometry"),
            SketchGeometryReference(OTHER_LINE_ID, "geometry"),
        ),
    )
    perpendicular_result = solve_sketch_constraint(sketch, perpendicular)
    assert perpendicular_result.status == "success", perpendicular_result.message

    angle = SketchConstraint(
        OTHER_CIRCLE_ID,
        "angle",
        (
            SketchGeometryReference(LINE_ID, "geometry"),
            SketchGeometryReference(OTHER_LINE_ID, "geometry"),
        ),
        45.0,
        "deg",
    )
    angle_result = solve_sketch_constraint(sketch, angle)
    assert angle_result.status == "success", angle_result.message

    coincident = SketchConstraint(
        OTHER_CIRCLE_ID,
        "coincident",
        (
            SketchGeometryReference(LINE_ID, "end"),
            SketchGeometryReference(OTHER_LINE_ID, "start"),
        ),
    )
    coincident_result = solve_sketch_constraint(sketch, coincident)
    assert coincident_result.status == "success", coincident_result.message

    circle_sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (
            CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0),
            CircleEntity(OTHER_CIRCLE_ID, (20.0, 0.0), 8.0),
        ),
    )
    equal = SketchConstraint(
        LENGTH_ID,
        "equal",
        (
            SketchGeometryReference(CIRCLE_ID, "geometry"),
            SketchGeometryReference(OTHER_CIRCLE_ID, "geometry"),
        ),
    )
    equal_result = solve_sketch_constraint(circle_sketch, equal)
    assert equal_result.status == "success", equal_result.message
    assert equal_result.sketch is not None
    first, second = equal_result.sketch.entities
    assert isinstance(first, CircleEntity)
    assert isinstance(second, CircleEntity)
    assert first.radius_mm == pytest.approx(second.radius_mm, abs=1e-6)

    concentric = SketchConstraint(
        LENGTH_ID,
        "concentric",
        (
            SketchGeometryReference(CIRCLE_ID, "geometry"),
            SketchGeometryReference(OTHER_CIRCLE_ID, "geometry"),
        ),
    )
    concentric_result = solve_sketch_constraint(circle_sketch, concentric)
    assert concentric_result.status == "success", concentric_result.message
    assert concentric_result.sketch is not None
    first_center, second_center = concentric_result.sketch.entities
    assert isinstance(first_center, CircleEntity)
    assert isinstance(second_center, CircleEntity)
    assert first_center.center_mm == pytest.approx(second_center.center_mm, abs=1e-6)

    radius = SketchConstraint(
        LENGTH_ID,
        "diameter",
        (SketchGeometryReference(CIRCLE_ID, "geometry"),),
        12.0,
        "mm",
    )
    diameter_result = solve_sketch_constraint(
        Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0),)),
        radius,
    )
    assert diameter_result.status == "success", diameter_result.message
    assert diameter_result.sketch is not None
    solved_circle = diameter_result.sketch.entities[0]
    assert isinstance(solved_circle, CircleEntity)
    assert solved_circle.radius_mm == pytest.approx(6.0, abs=1e-6)


def test_arc_dimension_preserves_clockwise_sweep() -> None:
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (ArcEntity(ARC_ID, (0.0, 0.0), 10.0, 20.0, -90.0),),
    )
    constraint = SketchConstraint(
        LENGTH_ID,
        "radius",
        (SketchGeometryReference(ARC_ID, "geometry"),),
        15.0,
        "mm",
    )

    result = solve_sketch_constraint(sketch, constraint)

    assert result.status == "success", result.message
    assert result.sketch is not None
    solved_arc = result.sketch.entities[0]
    assert isinstance(solved_arc, ArcEntity)
    assert solved_arc.radius_mm == pytest.approx(15.0, abs=1e-6)
    assert solved_arc.sweep_angle_deg == pytest.approx(-90.0, abs=1e-6)


@pytest.mark.parametrize("scale", (0.01, 1.0, 1_000.0, 100_000.0))
def test_driving_length_residual_stays_within_scale_tolerance(scale: float) -> None:
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(LINE_ID, (0.0, 0.0), (scale, scale * 0.2)),),
    )
    constraint = SketchConstraint(
        LENGTH_ID,
        "length",
        (SketchGeometryReference(LINE_ID, "geometry"),),
        scale,
        "mm",
    )

    result = solve_sketch_constraint(sketch, constraint)

    assert result.status == "success", result.message
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, LineEntity)
    assert hypot(solved.end_mm[0] - solved.start_mm[0], solved.end_mm[1] - solved.start_mm[1]) == (
        pytest.approx(scale, rel=1e-9, abs=1e-12)
    )


def test_anchored_extreme_scale_solution_is_accurate_without_mutating_input() -> None:
    scale = 1_000_000.0
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(LINE_ID, (0.0, 0.0), (scale, scale * 0.2)),),
    )
    constraint = SketchConstraint(
        LENGTH_ID,
        "length",
        (SketchGeometryReference(LINE_ID, "geometry"),),
        scale,
        "mm",
    )

    result = solve_sketch_constraint(sketch, constraint)

    assert result.status == "success", result.message
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, LineEntity)
    assert hypot(
        solved.end_mm[0] - solved.start_mm[0], solved.end_mm[1] - solved.start_mm[1]
    ) == pytest.approx(scale, rel=1e-9)
    assert solved.start_mm == pytest.approx((0, 0))
    original_line = sketch.entities[0]
    assert isinstance(original_line, LineEntity)
    assert original_line.start_mm == (0.0, 0.0)


def test_small_dimension_perturbations_keep_the_seeded_solution_branch() -> None:
    sketch = _line_sketch()
    fixed = SketchConstraint(
        HORIZONTAL_ID,
        "fixed",
        (SketchGeometryReference(LINE_ID, "start"),),
    )
    anchored = solve_sketch_constraint(sketch, fixed)
    assert anchored.status == "success", anchored.message
    assert anchored.sketch is not None

    solved_endpoints: list[tuple[float, float]] = []
    for index, target_length in enumerate((12.0, 12.01, 12.02)):
        dimension = SketchConstraint(
            f"{index + 10:08x}-0000-4000-8000-000000000000",
            "length",
            (SketchGeometryReference(LINE_ID, "geometry"),),
            target_length,
            "mm",
        )
        result = solve_sketch_constraint(anchored.sketch, dimension)
        assert result.status == "success", result.message
        assert result.sketch is not None
        solved = result.sketch.entities[0]
        assert isinstance(solved, LineEntity)
        solved_endpoints.append(solved.end_mm)

    assert all(endpoint[0] > 0.0 for endpoint in solved_endpoints)
    assert solved_endpoints[0][1] == pytest.approx(solved_endpoints[-1][1], abs=0.1)


def test_constraint_command_replays_undo_redo_and_archive_without_resolving(
    tmp_path: Path,
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = _line_sketch()
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    current = services.kernel.sketches[0]
    constraint = _constraint(LENGTH_ID, "length", value=20.0, unit="mm")
    result = solve_sketch_constraint(current, constraint)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success"
    assert result.sketch is not None
    params = result.command_params(current, constraint)

    loaded.bus.execute("sketch.constraint.add", params, confirmed_by="local")

    assert services.kernel.sketches[0].constraints == (constraint,)
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints == ()
    loaded.bus.redo()
    assert services.kernel.sketches[0].constraints == (constraint,)
    archive = tmp_path / "constrained.mc.json"
    save_document(loaded.document, archive)
    reopened = open_app_document(services, archive)
    assert reopened.document.commands[-1].id == "sketch.constraint.add"
    assert services.kernel.sketches[0].constraints == (constraint,)
    assert services.kernel.sketches[0].entities == result.sketch.entities


def test_constraint_regenerates_existing_extrusion_and_replays_without_solver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0),))
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": SKETCH_ID}, "distance": 10.0},
        confirmed_by="local",
    )
    current = services.kernel.sketches[0]
    constraint = SketchConstraint(
        LENGTH_ID, "radius", (SketchGeometryReference(CIRCLE_ID, "geometry"),), 7.0, "mm"
    )
    result = solve_sketch_constraint(current, constraint)
    assert result.status == "success", result.message

    def unexpected_solver(*_args: object, **_kwargs: object) -> None:
        pytest.fail("replay must use frozen solutions, never the optional solver")

    monkeypatch.setattr(sketch_constraint_adapter, "solve_sketch_constraint", unexpected_solver)
    loaded.bus.execute(
        "sketch.constraint.add", result.command_params(current, constraint), confirmed_by="local"
    )
    assert services.kernel.mass_properties().volume == pytest.approx(490.0 * math.pi)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(250.0 * math.pi)
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(490.0 * math.pi)
    archive = tmp_path / "regenerated.mc.json"
    save_document(loaded.document, archive)
    reopened = open_app_document(services, archive)
    assert reopened.document.commands[-1].version == 3
    assert services.kernel.mass_properties().volume == pytest.approx(490.0 * math.pi)


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_constraint_versions_preserve_existing_consumer_geometry(version: int) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0),))
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": SKETCH_ID}, "distance": 10.0},
        confirmed_by="local",
    )
    current = services.kernel.sketches[0]
    constraint = SketchConstraint(
        LENGTH_ID, "radius", (SketchGeometryReference(CIRCLE_ID, "geometry"),), 7.0, "mm"
    )
    result = solve_sketch_constraint(current, constraint)
    assert result.status == "success", result.message
    loaded.bus.execute(
        "sketch.constraint.add",
        result.command_params(current, constraint),
        confirmed_by="local",
        version=version,
    )
    assert services.kernel.sketches[0].entities != current.entities
    assert services.kernel.mass_properties().volume == pytest.approx(250.0 * math.pi)
    loaded.bus.undo()
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(250.0 * math.pi)


def test_constraint_rebuild_failure_restores_history_sketch_and_solid() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0), CircleEntity(OTHER_CIRCLE_ID, (0.0, 0.0), 2.0)),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": SKETCH_ID}, "distance": 10.0},
        confirmed_by="local",
    )
    current = services.kernel.sketches[0]
    commands = loaded.document.commands
    constraint = SketchConstraint(
        LENGTH_ID, "radius", (SketchGeometryReference(CIRCLE_ID, "geometry"),), 2.0, "mm"
    )
    result = solve_sketch_constraint(current, constraint)
    assert result.status == "success", result.message
    with pytest.raises(GeometryBuildError, match="轮廓") as failure:
        loaded.bus.execute(
            "sketch.constraint.add",
            result.command_params(current, constraint),
            confirmed_by="local",
        )
    assert failure.value.ordinal == 1
    assert failure.value.command_id == "feature.extrude"
    assert loaded.document.commands == commands
    assert services.kernel.sketches == (current,)
    assert services.kernel.mass_properties().volume == pytest.approx(210.0 * math.pi)
    loaded.bus.undo()
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(210.0 * math.pi)


def test_constraint_regenerates_multiple_consumers_and_accepts_next_constraint() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0),))
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    for distance, mode in ((10.0, "new"), (20.0, "add")):
        loaded.bus.execute(
            "feature.extrude",
            {
                "profile": {"type": "sketch", "sketch_id": SKETCH_ID},
                "distance": distance,
                "mode": mode,
            },
            confirmed_by="local",
        )
    radius = SketchConstraint(
        LENGTH_ID, "radius", (SketchGeometryReference(CIRCLE_ID, "geometry"),), 7.0, "mm"
    )
    center = SketchConstraint(
        HORIZONTAL_ID, "fixed", (SketchGeometryReference(CIRCLE_ID, "center"),)
    )
    for constraint in (radius, center):
        current = services.kernel.sketches[0]
        result = solve_sketch_constraint(current, constraint)
        assert result.status == "success", result.message
        loaded.bus.execute(
            "sketch.constraint.add",
            result.command_params(current, constraint),
            confirmed_by="local",
        )
        assert services.kernel.mass_properties().volume == pytest.approx(980.0 * math.pi)
    assert services.kernel.sketches[0].constraints == (radius, center)
    loaded.bus.undo(2)
    assert services.kernel.mass_properties().volume == pytest.approx(500.0 * math.pi)
    loaded.bus.redo(2)
    assert services.kernel.mass_properties().volume == pytest.approx(980.0 * math.pi)
    assert services.kernel.sketches[0].constraints == (radius, center)


def test_constraint_regeneration_preserves_attached_sketch_consumers() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    base = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0),))
    loaded.bus.execute("sketch.create", base.to_mapping(), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": SKETCH_ID}, "distance": 10.0},
        confirmed_by="local",
    )
    support = SketchSupportFace((0.0, 0.0, 10.0), "+Z")
    attached = Sketch(
        OTHER_LINE_ID,
        WorkPlaneFrame.from_planar_face((0.0, 0.0, 10.0), (0.0, 0.0, 1.0)),
        (CircleEntity(OTHER_CIRCLE_ID, (0.0, 0.0), 1.0),),
        support_face=support,
    )
    loaded.bus.execute("sketch.create", attached.to_mapping(), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": OTHER_LINE_ID}, "distance": 4.0, "mode": "add"},
        confirmed_by="local",
    )
    current = services.kernel.sketches[0]
    constraint = SketchConstraint(
        LENGTH_ID, "radius", (SketchGeometryReference(CIRCLE_ID, "geometry"),), 7.0, "mm"
    )
    result = solve_sketch_constraint(current, constraint)
    assert result.status == "success", result.message
    loaded.bus.execute(
        "sketch.constraint.add", result.command_params(current, constraint), confirmed_by="local"
    )
    assert services.kernel.mass_properties().volume == pytest.approx(494.0 * math.pi)
    regenerated = services.kernel.sketches[1]
    assert regenerated.entities == attached.entities
    assert regenerated.support_face == attached.support_face
    assert regenerated.frame.origin_mm == pytest.approx(attached.frame.origin_mm, abs=1e-9)
    assert regenerated.frame.u_axis == pytest.approx(attached.frame.u_axis, abs=1e-9)
    assert regenerated.frame.normal == pytest.approx(attached.frame.normal, abs=1e-9)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(254.0 * math.pi)
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(494.0 * math.pi)


def test_reopened_model_can_regenerate_a_second_sketch(tmp_path: Path) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    for sketch_id, entity_id, center, radius, mode in (
        (SKETCH_ID, CIRCLE_ID, (0.0, 0.0), 5.0, "new"),
        (OTHER_LINE_ID, OTHER_CIRCLE_ID, (20.0, 0.0), 2.0, "add"),
    ):
        sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (CircleEntity(entity_id, center, radius),))
        loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
        loaded.bus.execute(
            "feature.extrude",
            {"profile": {"type": "sketch", "sketch_id": sketch_id}, "distance": 10.0, "mode": mode},
            confirmed_by="local",
        )
    for index, entity_id, constraint_id, radius in (
        (0, CIRCLE_ID, LENGTH_ID, 7.0),
        (1, OTHER_CIRCLE_ID, HORIZONTAL_ID, 3.0),
    ):
        current = services.kernel.sketches[index]
        constraint = SketchConstraint(
            constraint_id, "radius", (SketchGeometryReference(entity_id, "geometry"),), radius, "mm"
        )
        result = solve_sketch_constraint(current, constraint)
        assert result.status == "success", result.message
        loaded.bus.execute(
            "sketch.constraint.add",
            result.command_params(current, constraint),
            confirmed_by="local",
        )
        archive = tmp_path / "multiple-sketches.mc.json"
        save_document(loaded.document, archive)
        loaded = open_app_document(services, archive)
    assert services.kernel.mass_properties().volume == pytest.approx(580.0 * math.pi)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(530.0 * math.pi)
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(580.0 * math.pi)


def test_constraint_command_rejects_stale_preview_without_history_change() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = _line_sketch()
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    current = services.kernel.sketches[0]
    constraint = _constraint(LENGTH_ID, "length", value=20.0, unit="mm")
    result = solve_sketch_constraint(current, constraint)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success"
    assert result.sketch is not None
    params = result.command_params(current, constraint)
    params["base_state_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="stale"):
        loaded.bus.execute("sketch.constraint.add", params, confirmed_by="local")

    assert len(loaded.document.commands) == 1
    assert services.kernel.sketches == (sketch,)


def test_existing_dimension_update_preserves_later_relations_and_rebuilds_without_solver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    radius = SketchConstraint(
        LENGTH_ID, "radius", (SketchGeometryReference(CIRCLE_ID, "geometry"),), 5.0, "mm"
    )
    diameter = SketchConstraint(
        VERTICAL_ID,
        "diameter",
        (SketchGeometryReference(CIRCLE_ID, "geometry"),),
        10.0,
        "mm",
        driving=False,
    )
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0),),
        (radius, diameter),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": SKETCH_ID}, "distance": 10.0},
        confirmed_by="local",
    )
    fixed = SketchConstraint(
        HORIZONTAL_ID, "fixed", (SketchGeometryReference(CIRCLE_ID, "center"),)
    )
    current = services.kernel.sketches[0]
    result = solve_sketch_constraint(current, fixed)
    assert result.status == "success", result.message
    loaded.bus.execute(
        "sketch.constraint.add", result.command_params(current, fixed), confirmed_by="local"
    )
    original_origin = services.kernel.viewport_data()[-1].body_origins[0]
    assert original_origin.result.state_id == "feature.extrude:1"
    original_commands = loaded.document.commands
    current = services.kernel.sketches[0]
    revised = replace(radius, value=7.0, precision=3)
    result = services.kernel.preview_sketch_constraint_update(current, revised)
    assert result.status == "success", result.message
    assert result.sketch is not None
    assert result.sketch.constraints == (revised, replace(diameter, value=14.0), fixed)
    assert services.kernel.sketches[0] == current

    def unexpected_solver(*_args: object, **_kwargs: object) -> None:
        pytest.fail("replaying a dimension revision must not invoke the solver")

    monkeypatch.setattr(sketch_constraint_adapter, "solve_sketch_constraint", unexpected_solver)
    monkeypatch.setattr(
        sketch_constraint_adapter, "solve_sketch_constraint_update", unexpected_solver
    )
    loaded.bus.execute(
        "sketch.constraint.update", result.command_params(current, revised), confirmed_by="local"
    )
    rebuilt_origin = services.kernel.viewport_data()[-1].body_origins[0]
    assert rebuilt_origin.result.state_id == "sketch.constraint.update:3"
    assert tuple(item.result for item in rebuilt_origin.inputs) == (original_origin.result,)
    assert tuple(item.role for item in rebuilt_origin.inputs) == ("model",)
    assert loaded.document.commands[:-1] == original_commands
    assert services.kernel.sketches[0] == result.sketch
    assert services.kernel.mass_properties().volume == pytest.approx(490.0 * math.pi)
    loaded.bus.undo()
    assert services.kernel.viewport_data()[-1].body_origins[0].result == original_origin.result
    assert services.kernel.sketches[0] == current
    assert services.kernel.mass_properties().volume == pytest.approx(250.0 * math.pi)
    loaded.bus.redo()
    assert services.kernel.viewport_data()[-1].body_origins[0].result == rebuilt_origin.result
    assert services.kernel.sketches[0] == result.sketch
    archive = tmp_path / "dimension-revision.mc.json"
    save_document(loaded.document, archive)
    reopened = open_app_document(services, archive)
    assert reopened.document.commands[-1].id == "sketch.constraint.update"
    assert services.kernel.sketches[0] == result.sketch
    assert services.kernel.mass_properties().volume == pytest.approx(490.0 * math.pi)

    reopened_origin = services.kernel.viewport_data()[-1].body_origins[0]
    assert reopened_origin.result == rebuilt_origin.result
    assert reopened_origin.inputs == rebuilt_origin.inputs


def test_existing_dimension_update_rolls_back_an_invalid_downstream_profile() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    dimension = SketchConstraint(
        LENGTH_ID, "radius", (SketchGeometryReference(CIRCLE_ID, "geometry"),), 5.0, "mm"
    )
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0), CircleEntity(OTHER_CIRCLE_ID, (0.0, 0.0), 2.0)),
        (dimension,),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": SKETCH_ID}, "distance": 10.0},
        confirmed_by="local",
    )
    commands = loaded.document.commands
    current = services.kernel.sketches[0]
    revision = replace(dimension, value=2.0)
    result = services.kernel.preview_sketch_constraint_update(current, revision)
    assert result.status == "success", result.message
    with pytest.raises(GeometryBuildError, match="轮廓"):
        loaded.bus.execute(
            "sketch.constraint.update",
            result.command_params(current, revision),
            confirmed_by="local",
        )
    assert loaded.document.commands == commands
    assert services.kernel.sketches == (current,)
    assert services.kernel.mass_properties().volume == pytest.approx(210.0 * math.pi)


@pytest.mark.parametrize("kind", ["length", "distance", "angle", "radius", "diameter"])
def test_each_dimension_kind_can_be_revised_from_current_geometry(kind: ConstraintKind) -> None:
    entities: tuple[SketchEntity, ...]
    references: tuple[SketchGeometryReference, ...]
    unit: ConstraintUnit = "mm"
    if kind in ("radius", "diameter"):
        entities = (CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0),)
        references = (SketchGeometryReference(CIRCLE_ID, "geometry"),)
        before, after = (5.0, 7.0) if kind == "radius" else (10.0, 14.0)
    elif kind == "angle":
        entities = (
            LineEntity(LINE_ID, (0.0, 0.0), (10.0, 0.0)),
            LineEntity(OTHER_LINE_ID, (0.0, 0.0), (0.0, 10.0)),
        )
        references = (
            SketchGeometryReference(LINE_ID, "geometry"),
            SketchGeometryReference(OTHER_LINE_ID, "geometry"),
        )
        before, after, unit = 90.0, 60.0, "deg"
    else:
        entities = (LineEntity(LINE_ID, (0.0, 0.0), (10.0, 0.0)),)
        references = (
            (SketchGeometryReference(LINE_ID, "geometry"),)
            if kind == "length"
            else (
                SketchGeometryReference(LINE_ID, "start"),
                SketchGeometryReference(LINE_ID, "end"),
            )
        )
        before, after = 10.0, 15.0
    original = SketchConstraint(LENGTH_ID, kind, references, before, unit)
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), entities, (original,))
    revised = replace(original, value=after)
    result = sketch_constraint_adapter.solve_sketch_constraint_update(sketch, revised)
    assert result.status == "success", result.message
    assert result.sketch is not None
    assert result.sketch.constraints == (revised,)
    assert sketch_constraint_adapter.measure_sketch_dimension(
        result.sketch, revised
    ) == pytest.approx(after, abs=1e-7)
    assert sketch.constraints == (original,)


def test_new_driving_dimension_refreshes_existing_reference_annotation() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    reference = SketchConstraint(
        VERTICAL_ID,
        "diameter",
        (SketchGeometryReference(CIRCLE_ID, "geometry"),),
        10.0,
        "mm",
        driving=False,
    )
    sketch = Sketch(
        SKETCH_ID, WorkPlaneFrame.xy(), (CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0),), (reference,)
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    radius = SketchConstraint(
        LENGTH_ID, "radius", (SketchGeometryReference(CIRCLE_ID, "geometry"),), 7.0, "mm"
    )
    current = services.kernel.sketches[0]
    result = services.kernel.preview_sketch_constraint(current, radius)
    assert result.status == "success", result.message
    loaded.bus.execute(
        "sketch.constraint.add", result.command_params(current, radius), confirmed_by="local"
    )
    assert services.kernel.sketches[0].constraints[0].value == pytest.approx(14.0)
    assert services.kernel.sketches[0] == result.sketch
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints[0].value == pytest.approx(10.0)
    loaded.bus.redo()
    assert services.kernel.sketches[0].constraints[0].value == pytest.approx(14.0)


def test_drawing_dimension_can_switch_reference_and_driving_modes(tmp_path: Path) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    dimension = SketchConstraint(
        LENGTH_ID, "radius", (SketchGeometryReference(CIRCLE_ID, "geometry"),), 5.0, "mm"
    )
    sketch = Sketch(
        SKETCH_ID, WorkPlaneFrame.xy(), (CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0),), (dimension,)
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    for revision in (replace(dimension, driving=False, value=None), replace(dimension, value=7.0)):
        current = services.kernel.sketches[0]
        result = services.kernel.preview_sketch_constraint_update(current, revision)
        assert result.status == "success", result.message
        loaded.bus.execute(
            "sketch.constraint.update",
            result.command_params(current, revision),
            confirmed_by="local",
        )
        assert len(services.kernel.sketches[0].constraints) == 1
    assert services.kernel.sketches[0].constraints[0] == replace(dimension, value=7.0)
    archive = tmp_path / "drawing-revision.mc.json"
    save_document(loaded.document, archive)
    loaded = open_app_document(services, archive)
    assert loaded.document.document_type == "drawing2d"
    loaded.bus.undo()
    measured = services.kernel.sketches[0].constraints[0]
    assert not measured.driving
    assert measured.value == pytest.approx(5.0)


def _locked_sketch(
    *entities: SketchEntity, constraints: tuple[SketchConstraint, ...] = ()
) -> Sketch:
    return Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        entities,
        constraints,
        SketchLayerTable().add(SketchLayer("locked", locked=True)),
    )


def test_locked_layer_blocks_driving_add_update_and_drag_but_allows_reference() -> None:
    circle = CircleEntity(CIRCLE_ID, (0.0, 0.0), 5.0, layer_name="locked")
    reference = SketchGeometryReference(CIRCLE_ID, "geometry")
    radius = SketchConstraint(LENGTH_ID, "radius", (reference,), value=5.0, unit="mm")
    sketch = _locked_sketch(circle)
    changed = replace(radius, value=7.0)
    added = solve_sketch_constraint(sketch, changed)
    assert added.status == "invalid" and added.sketch is None
    assert added.message is not None and "锁定" in added.message
    updated = sketch_constraint_adapter.solve_sketch_constraint_update(
        replace(sketch, constraints=(radius,)), changed
    )
    assert updated.status == "invalid" and updated.sketch is None
    dragged = solve_sketch_drag(sketch, SketchGeometryReference(CIRCLE_ID, "center"), (2.0, 3.0))
    assert dragged.status == "invalid" and dragged.sketch is None
    measured = solve_sketch_constraint(sketch, replace(radius, driving=False))
    assert measured.status == "success", measured.message
    assert measured.sketch is not None
    assert measured.sketch.entities == sketch.entities
    assert measured.sketch.constraints[0].value == 5.0
    unlocked = replace(sketch, layers=SketchLayerTable().add(SketchLayer("locked")))
    recovered = solve_sketch_constraint(unlocked, changed)
    assert recovered.status == "success", recovered.message
    assert recovered.sketch is not None
    recovered_circle = recovered.sketch.entities[0]
    assert isinstance(recovered_circle, CircleEntity)
    assert recovered_circle.radius_mm == pytest.approx(7.0)
    assert sketch.entities == (circle,)


@pytest.mark.parametrize("drag", [False, True])
def test_locked_geometry_stays_fixed_when_unlocked_neighbor_is_solved(drag: bool) -> None:
    locked = LineEntity(LINE_ID, (0.0, 0.0), (10.0, 0.0), layer_name="locked")
    free = LineEntity(OTHER_LINE_ID, (10.0, 0.0), (20.0, 0.0))
    coincident = SketchConstraint(
        HORIZONTAL_ID,
        "coincident",
        (SketchGeometryReference(LINE_ID, "end"), SketchGeometryReference(OTHER_LINE_ID, "start")),
    )
    sketch = _locked_sketch(locked, free, constraints=(coincident,))
    result = (
        solve_sketch_drag(sketch, SketchGeometryReference(OTHER_LINE_ID, "start"), (15.0, 0.0))
        if drag
        else solve_sketch_constraint(
            sketch,
            SketchConstraint(
                LENGTH_ID,
                "length",
                (SketchGeometryReference(OTHER_LINE_ID, "geometry"),),
                value=20.0,
                unit="mm",
            ),
        )
    )
    assert result.status == "success", result.message
    assert result.sketch is not None
    assert result.sketch.entities[0] == locked
    solved_free = result.sketch.entities[1]
    assert isinstance(solved_free, LineEntity)
    assert solved_free.start_mm == pytest.approx((10.0, 0.0))
    if not drag:
        assert math.dist(solved_free.start_mm, solved_free.end_mm) == pytest.approx(20.0)


@pytest.mark.parametrize(
    "locked",
    [
        LineEntity(LINE_ID, (0.0, 0.0), (10.0, 0.0), layer_name="locked"),
        PolylineEntity(LINE_ID, ((0.0, 0.0), (10.0, 0.0), (10.0, 5.0)), layer_name="locked"),
        RectangleEntity(LINE_ID, (0.0, 0.0), (10.0, 5.0), layer_name="locked"),
        CircleEntity(LINE_ID, (0.0, 0.0), 5.0, layer_name="locked"),
        ArcEntity(LINE_ID, (0.0, 0.0), 5.0, 123.0, -220.0, layer_name="locked"),
    ],
)
def test_all_locked_entity_parameters_are_constants(locked: SketchEntity) -> None:
    free = LineEntity(OTHER_LINE_ID, (30.0, 0.0), (40.0, 0.0))
    sketch = _locked_sketch(locked, free)
    result = solve_sketch_constraint(
        sketch,
        SketchConstraint(
            LENGTH_ID,
            "length",
            (SketchGeometryReference(OTHER_LINE_ID, "geometry"),),
            value=20.0,
            unit="mm",
        ),
    )
    assert result.status == "success", result.message
    assert result.sketch is not None
    assert result.sketch.entities[0] == locked
    assert result.degrees_of_freedom == 3


@pytest.mark.parametrize("reverse_arc", [False, True])
@pytest.mark.parametrize("polyline_line", [False, True])
def test_local_fillet_endpoints_follow_source_radius_dimension(
    reverse_arc: bool, polyline_line: bool
) -> None:
    from uuid import uuid4

    x = -math.sqrt(7)
    line = (
        PolylineEntity(LINE_ID, ((-20, 0), (x, 0)))
        if polyline_line
        else LineEntity(LINE_ID, (-20, 0), (x, 0))
    )
    circle = CircleEntity(CIRCLE_ID, (0, 5), 2)
    arc = ArcEntity(
        ARC_ID,
        (x, 2),
        2,
        48.59037789072914 if reverse_arc else -90,
        -138.59037789072914 if reverse_arc else 138.59037789072914,
    )
    line_tangent = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(
                line.entity_id,
                "segment" if polyline_line else "geometry",
                0 if polyline_line else None,
            ),
            SketchGeometryReference(arc.entity_id, "geometry"),
        ),
        source="inferred",
        first_endpoint="end",
        second_endpoint="end" if reverse_arc else "start",
    )
    circle_tangent = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(circle.entity_id, "geometry"),
            SketchGeometryReference(arc.entity_id, "geometry"),
        ),
        source="inferred",
        second_endpoint="start" if reverse_arc else "end",
    )
    coincident = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(
                line.entity_id, "vertex" if polyline_line else "end", 1 if polyline_line else None
            ),
            SketchGeometryReference(arc.entity_id, "end" if reverse_arc else "start"),
        ),
        source="inferred",
    )
    sketch = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (line, circle, arc),
        (line_tangent, circle_tangent, coincident),
    )
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 2.5, "mm"
    )
    result = solve_sketch_constraint(sketch, dimension)
    assert result.status == "success", result.message
    assert result.sketch is not None
    from mycad.geom.sketch_constraints import validate_sketch_revision_geometry

    validate_sketch_revision_geometry(sketch, result.sketch)
    new_line, new_circle, new_arc = result.sketch.entities
    assert (
        isinstance(new_line, LineEntity | PolylineEntity)
        and isinstance(new_circle, CircleEntity)
        and isinstance(new_arc, ArcEntity)
    )
    assert new_circle.radius_mm == pytest.approx(2.5)
    angle = math.radians(new_arc.start_angle_deg + (new_arc.sweep_angle_deg if reverse_arc else 0))
    line_end = new_line.end_mm if isinstance(new_line, LineEntity) else new_line.points_mm[-1]
    assert line_end == pytest.approx(
        (
            new_arc.center_mm[0] + new_arc.radius_mm * math.cos(angle),
            new_arc.center_mm[1] + new_arc.radius_mm * math.sin(angle),
        )
    )
    dragged = solve_sketch_drag(
        sketch, SketchGeometryReference(circle.entity_id, "center"), (0, 5.4)
    )
    assert dragged.status == "success", dragged.message
    assert dragged.sketch is not None
    validate_sketch_revision_geometry(sketch, dragged.sketch)
    if not reverse_arc and not polyline_line:
        fixed_circle = SketchConstraint(
            uuid4().hex, "fixed", (SketchGeometryReference(circle.entity_id, "center"),)
        )
        fixed_arc = SketchConstraint(
            uuid4().hex, "fixed", (SketchGeometryReference(arc.entity_id, "center"),)
        )
        fixed_radius = SketchConstraint(
            uuid4().hex,
            "radius",
            (SketchGeometryReference(arc.entity_id, "geometry"),),
            2,
            "mm",
        )
        blocked = replace(
            sketch, constraints=(*sketch.constraints, fixed_circle, fixed_arc, fixed_radius)
        )
        result = solve_sketch_constraint(blocked, dimension)
        assert result.status != "success"
        assert blocked.entities == sketch.entities


@pytest.mark.parametrize("valid", [False, True])
def test_initial_local_endpoint_tangency_validates_declared_contact(
    tmp_path: Path, valid: bool
) -> None:
    line = LineEntity(LINE_ID, (-10, 0), (0, 0))
    arc = ArcEntity(ARC_ID, (0, 2), 2, -90, 90)
    relation = SketchConstraint(
        HORIZONTAL_ID,
        "tangent",
        (SketchGeometryReference(LINE_ID, "geometry"), SketchGeometryReference(ARC_ID, "geometry")),
        source="inferred",
        first_endpoint="end",
        second_endpoint="start" if valid else "end",
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line, arc), (relation,))
    services = build_app(discoverers=[])
    loaded = new_document(services)
    if not valid:
        with pytest.raises(ValidationError):
            commit_new_sketch(services, loaded, sketch, session_identity=1)
        assert not loaded.document.commands
        return
    commit_new_sketch(services, loaded, sketch, session_identity=1)
    assert loaded.document.commands[-1].version == 13
    path = tmp_path / "local-fillet.mc.json"
    save_document(loaded.document, path)
    open_app_document(services, path)
    assert services.kernel.sketches[0].constraints == (relation,)


def test_endpoint_constraint_replay_rejects_tampered_solved_geometry() -> None:
    from copy import deepcopy
    from uuid import uuid4

    line = LineEntity(LINE_ID, (-10, 0), (0, 0))
    arc = ArcEntity(ARC_ID, (0, 2), 2, -90, 90)
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (SketchGeometryReference(LINE_ID, "geometry"), SketchGeometryReference(ARC_ID, "geometry")),
        source="inferred",
        first_endpoint="end",
        second_endpoint="start",
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line, arc), (relation,))
    services = build_app(discoverers=[])
    loaded = new_document(services)
    commit_new_sketch(services, loaded, sketch, session_identity=0)
    source = services.kernel.sketches[0]
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(ARC_ID, "geometry"),), 3, "mm"
    )
    preview = services.kernel.preview_sketch_constraint(source, dimension)
    assert preview.status == "success", preview.message
    params = deepcopy(preview.command_params(source, dimension))
    entities = cast("list[dict[str, object]]", params["solution_entities"])
    arc_data = next(item for item in entities if item["entity_id"] == ARC_ID)
    arc_data["start_angle_deg"] = 0
    before = tuple(loaded.document.commands)
    with pytest.raises(ValidationError):
        loaded.bus.execute("sketch.constraint.add", params, "local", version=3)
    assert tuple(loaded.document.commands) == before
    assert services.kernel.sketches == (source,)


def test_explicit_local_endpoint_tangency_add_replays_through_bus(tmp_path: Path) -> None:
    from uuid import uuid4

    line = LineEntity(LINE_ID, (-10, 0), (0, 0))
    arc = ArcEntity(ARC_ID, (0, 2), 2, -90, 90)
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line, arc))
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    # An initial connected relation upgrades the document to archive version 6.
    initial = SketchConstraint(
        uuid4().hex,
        "tangent",
        (SketchGeometryReference(LINE_ID, "geometry"), SketchGeometryReference(ARC_ID, "geometry")),
        source="inferred",
        first_endpoint="end",
        second_endpoint="start",
    )
    # Use a separate endpoint-free sketch to avoid duplicating the new relation.
    commit_new_sketch(services, loaded, replace(sketch, constraints=(initial,)), session_identity=0)
    loaded.bus.undo()
    assert not services.kernel.sketches
    commit_new_sketch(services, loaded, sketch, session_identity=0)
    source = services.kernel.sketches[0]
    relation = replace(initial, source="user")
    result = services.kernel.preview_sketch_constraint(source, relation)
    assert result.status == "success", result.message
    loaded.bus.execute(
        "sketch.constraint.add",
        result.command_params(source, relation, local_frame=True),
        "local",
        version=5,
    )
    assert services.kernel.sketches[0].constraints == (relation,)
    loaded.bus.undo()
    assert services.kernel.sketches[0] == source
    loaded.bus.redo()
    path = tmp_path / "local-tangent-add.my2d"
    save_document(loaded.document, path)
    open_app_document(services, path)
    assert services.kernel.sketches[0].constraints == (relation,)


def test_single_sketch_revision_can_add_inferred_endpoint_fillet() -> None:
    from uuid import uuid4

    from mycad.core.line_fillet import line_fillet

    first = LineEntity(LINE_ID, (0, 0), (10, 0))
    second = LineEntity(OTHER_LINE_ID, (0, 0), (0, 10))
    before = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (first, second))
    first_result, second_result, arc = line_fillet(first, second, (8, 0), (0, 8), 2, ARC_ID)
    first_relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (SketchGeometryReference(LINE_ID, "geometry"), SketchGeometryReference(ARC_ID, "geometry")),
        source="inferred",
        first_endpoint="start",
        second_endpoint="start",
    )
    second_relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(OTHER_LINE_ID, "geometry"),
            SketchGeometryReference(ARC_ID, "geometry"),
        ),
        source="inferred",
        first_endpoint="start",
        second_endpoint="end",
    )
    after = replace(
        before,
        entities=(first_result, second_result, arc),
        constraints=(first_relation, second_relation),
    )
    state = after.to_state_mapping()
    revision: dict[str, object] = {
        "sketch_id": before.sketch_id,
        "base_state_sha256": before.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    commit_new_sketch(services, loaded, before, session_identity=0)
    from mycad import app
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet

    candidate = app.create_replay_candidate(services, loaded, session_identity=0)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("sketch.revise", 4, revision, "local"),),
            False,
            target_archive_version=6,
        ),
        current_session_identity=0,
    )
    preview = candidate.preview(current_session_identity=0)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=0), current_session_identity=0
    )
    assert services.kernel.sketches == (after,)
    loaded.bus.undo()
    assert services.kernel.sketches == (before,)
    loaded.bus.redo()
    assert services.kernel.sketches == (after,)


def test_rectangle_segment_tangent_constraint_solves() -> None:
    from uuid import uuid4

    from mycad.core.cross_sketch_tangency import tangent_entity_curve
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.sketch import RectangleEntity

    rectangle = RectangleEntity(uuid4().hex, (-10, 0), (10, -10))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle, circle))
    tangent = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(rectangle.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    result = solve_sketch_constraint(sketch, tangent)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    assert result.sketch is not None
    moved_rectangle, moved_circle = result.sketch.entities
    assert isinstance(moved_rectangle, RectangleEntity) and isinstance(moved_circle, CircleEntity)
    assert tangent_on_curves(tangent_entity_curve(moved_rectangle, 0), moved_circle)
