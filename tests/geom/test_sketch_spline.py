# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Spline control data agree with OCCT, DXF, Bus replay and closed profiles."""

from pathlib import Path
from uuid import uuid4

import pytest

from mycad.app import build_app, new_document, open_app_document
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, SplineEntity, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.core.sketch_edit import copy_entities, move_sketch_handle
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf
from mycad.geom.sketch_profiles import spline_edge


@pytest.mark.parametrize("count", [4, 5, 7])
@pytest.mark.parametrize("frame", [WorkPlaneFrame.xy(), WorkPlaneFrame.xz()])
def test_spline_samples_match_exact_occt_curve(count: int, frame: WorkPlaneFrame) -> None:
    entity = SplineEntity(
        uuid4().hex, tuple((float(i * 10), float((i % 3) * 12)) for i in range(count))
    )
    sketch = Sketch(uuid4().hex, frame, (entity,))
    edge = spline_edge(sketch, entity)
    for parameter in (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0):
        expected = frame.local_to_world(
            entity.point_at(min(1.0, max(0.0, edge.param_at(parameter))))
        )
        actual = edge.position_at(parameter)
        assert pytest.approx(expected, abs=1e-8) == (actual.X, actual.Y, actual.Z)
    assert entity.point_at(0.0) == entity.control_points_mm[0]
    assert entity.point_at(1.0) == entity.control_points_mm[-1]


def test_spline_bus_replay_dxf_and_extrusion(tmp_path: Path) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    curve = SplineEntity(uuid4().hex, ((0.0, 0.0), (0.0, 20.0), (30.0, 20.0), (30.0, 0.0)))
    baseline = LineEntity(uuid4().hex, (30.0, 0.0), (0.0, 0.0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve, baseline))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "test")
    assert services.kernel.sketches[0] == sketch
    displayed = services.kernel.sketch_display_data()[0].curves[0].points
    assert len(displayed) > 4
    dxf = tmp_path / "curve.dxf"
    assert write_sketch_dxf(sketch, dxf).complete
    imported = read_sketch_dxf(dxf)
    assert imported.report.complete
    assert imported.sketch.entities == sketch.entities
    loaded.bus.execute(
        "feature.extrude",
        {
            "profile": {"type": "sketch", "sketch_id": sketch.sketch_id},
            "distance": 5.0,
            "mode": "new",
        },
        "test",
        version=2,
    )
    volume = services.kernel.mass_properties().volume
    assert volume > 1000.0
    archive = tmp_path / "spline.mc.json"
    save_document(loaded.document, archive)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == 0.0
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(volume)
    reopened = open_app_document(services, archive)
    assert len(reopened.document.commands) == 2
    assert services.kernel.sketches[0] == sketch
    assert services.kernel.mass_properties().volume == pytest.approx(volume)


def test_control_point_edit_and_copy_preserve_curve_identity() -> None:
    curve = SplineEntity(uuid4().hex, ((0.0, 0.0), (0.0, 20.0), (30.0, 20.0), (30.0, 0.0)))
    updated = move_sketch_handle(
        (curve,), SketchGeometryReference(curve.entity_id, "vertex", 1), (5.0, 25.0)
    )
    assert isinstance(updated[0], SplineEntity)
    assert updated[0].entity_id == curve.entity_id
    assert updated[0].control_points_mm[1] == (5.0, 25.0)
    copied = copy_entities(updated, (curve.entity_id,), (40.0, 0.0))
    assert isinstance(copied[1], SplineEntity)
    assert copied[1].entity_id != curve.entity_id
    assert copied[1].point_at(0.5) == pytest.approx(
        (updated[0].point_at(0.5)[0] + 40.0, updated[0].point_at(0.5)[1])
    )
    with pytest.raises(ValueError, match="version 3"):
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,)).to_mapping(version=2)


def test_line_dimension_solve_preserves_unrelated_spline() -> None:
    from mycad.core.sketch_constraints import SketchConstraint
    from mycad.geom.sketch_constraints import solve_sketch_constraint

    curve = SplineEntity(uuid4().hex, ((0.0, 0.0), (0.0, 20.0), (30.0, 20.0), (30.0, 0.0)))
    line = LineEntity(uuid4().hex, (50.0, 0.0), (60.0, 0.0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve, line))
    length = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 20.0, "mm"
    )
    result = solve_sketch_constraint(sketch, length)
    assert result.status == "success", result.message
    assert result.sketch is not None
    assert result.sketch.entities[0] == curve
    changed = result.sketch.entities[1]
    assert isinstance(changed, LineEntity)
    assert (
        (changed.end_mm[0] - changed.start_mm[0]) ** 2
        + (changed.end_mm[1] - changed.start_mm[1]) ** 2
    ) ** 0.5 == pytest.approx(20.0)
