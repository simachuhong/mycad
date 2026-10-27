# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A released sketch profile drives deterministic, replayable extrusion."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import cast

import pytest

from mycad.app import build_app, new_document, open_app_document
from mycad.core.exceptions import GeometryBuildError, ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    WorkPlaneFrame,
)

SKETCH_ID = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
OUTER_ID = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
HOLE_ID = "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c"
CONSTRUCTION_ID = "3d3d3d3d-3d3d-4d3d-8d3d-3d3d3d3d3d3d"
INNER_ID = "4e4e4e4e-4e4e-4e4e-8e4e-4e4e4e4e4e4e"
ARC_ID_A = "5f5f5f5f-5f5f-4f5f-8f5f-5f5f5f5f5f5f"
ARC_ID_B = "6a6a6a6a-6a6a-4a6a-8a6a-6a6a6a6a6a6a"
REVOLVE_ID = "7b7b7b7b-7b7b-4b7b-8b7b-7b7b7b7b7b7b"


def _profile_sketch(frame: WorkPlaneFrame | None = None) -> Sketch:
    return Sketch(
        sketch_id=SKETCH_ID,
        frame=frame or WorkPlaneFrame.xy(),
        entities=(
            CircleEntity(OUTER_ID, (0.0, 0.0), 20.0),
            CircleEntity(HOLE_ID, (0.0, 0.0), 5.0),
            LineEntity(CONSTRUCTION_ID, (-25.0, 0.0), (25.0, 0.0), construction=True),
        ),
    )


def _extrude_params(distance_mm: float = 8.0) -> dict[str, object]:
    return {
        "profile": {"type": "sketch", "sketch_id": SKETCH_ID},
        "distance": distance_mm,
        "mode": "new",
    }


def test_sketch_extrude_preserves_holes_construction_geometry_and_replay(
    tmp_path: Path,
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = _profile_sketch()
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")

    loaded.bus.execute("feature.extrude", _extrude_params(), confirmed_by="local", version=2)
    expected_volume = math.pi * (20.0**2 - 5.0**2) * 8.0
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=2e-5)

    archive = tmp_path / "sketch-extrusion.mc.json"
    save_document(loaded.document, archive)
    reopened = open_app_document(services, archive)
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=2e-5)

    reopened.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(0.0)
    assert services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=2e-5)


def test_symmetric_sketch_extrude_centers_total_depth_about_profile_plane(tmp_path: Path) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = _profile_sketch()
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    params = _extrude_params(8.0)
    params["extent_mode"] = "symmetric"

    loaded.bus.execute("feature.extrude", params, confirmed_by="local", version=3)

    expected_volume = math.pi * (20.0**2 - 5.0**2) * 8.0
    assert loaded.document.commands[-1].version == 3
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=2e-5)
    assert services.kernel.mass_properties().center_of_mass[2] == pytest.approx(0.0, abs=1e-6)
    archive = tmp_path / "symmetric-sketch-extrusion.mc.json"
    save_document(loaded.document, archive)
    assert json.loads(archive.read_text(encoding="utf-8"))["commands"][-1]["version"] == 3
    reopened = open_app_document(services, archive)
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=2e-5)
    assert services.kernel.mass_properties().center_of_mass[2] == pytest.approx(0.0, abs=1e-6)

    reopened.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(0.0)
    reopened.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=2e-5)


@pytest.mark.parametrize("distance", [-8.0, 0.0])
def test_symmetric_sketch_extrude_rejects_nonpositive_total_depth_without_history_change(
    distance: float,
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute("sketch.create", _profile_sketch().to_mapping(), confirmed_by="local")
    history_before = loaded.document.commands
    params = _extrude_params(distance)
    params["extent_mode"] = "symmetric"

    with pytest.raises(ValidationError, match="symmetric"):
        loaded.bus.execute("feature.extrude", params, confirmed_by="local", version=3)

    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(0.0)
    assert loaded.document.commands == history_before


def test_sketch_extrude_to_face_uses_selected_planar_face_and_replays(
    tmp_path: Path,
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute(
        "feature.box",
        {"size_x": 50.0, "size_y": 50.0, "size_z": 20.0, "center": [0.0, 0.0, 15.0]},
        confirmed_by="local",
    )
    selector = next(
        services.kernel.interactive_face_selector(face.topology_id)
        for face in services.kernel.viewport_data()[-1].faces
        if services.kernel.interactive_face_frame(face.topology_id).normal
        == pytest.approx((0.0, 0.0, 1.0))
    )
    center_mm = cast("list[object]", selector["center_mm"])
    target_z = float(cast("float", center_mm[2]))
    sketch = _profile_sketch()
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    params = {
        "profile": {"type": "sketch", "sketch_id": SKETCH_ID},
        "mode": "new",
        "extent_mode": "to_face",
        "target_face": selector,
    }

    loaded.bus.execute("feature.extrude", params, confirmed_by="local", version=4)

    expected_volume = math.pi * (20.0**2 - 5.0**2) * target_z
    assert loaded.document.commands[-1].version == 4
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=2e-5)
    archive = tmp_path / "to-face-sketch-extrusion.mc.json"
    save_document(loaded.document, archive)
    reopened = open_app_document(services, archive)
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=2e-5)
    reopened.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(50.0 * 50.0 * 20.0)
    reopened.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=2e-5)


def test_sketch_extrude_uses_selected_workplane_frame_and_signed_direction() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    frame = WorkPlaneFrame.xz()
    frame = WorkPlaneFrame(
        origin_mm=(0.0, 6.0, 0.0),
        u_axis=frame.u_axis,
        v_axis=frame.v_axis,
        normal=frame.normal,
    )
    sketch = Sketch(
        sketch_id=SKETCH_ID,
        frame=frame,
        entities=(CircleEntity(OUTER_ID, (0.0, 0.0), 4.0),),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    loaded.bus.execute("feature.extrude", _extrude_params(3.0), confirmed_by="local", version=2)

    props = services.kernel.mass_properties()
    assert props.volume == pytest.approx(math.pi * 4.0**2 * 3.0, rel=2e-5)
    assert props.center_of_mass[1] == pytest.approx(7.5, abs=1e-5)

    loaded.bus.undo()
    loaded.bus.execute("feature.extrude", _extrude_params(-3.0), confirmed_by="local", version=2)
    props = services.kernel.mass_properties()
    assert props.volume == pytest.approx(math.pi * 4.0**2 * 3.0, rel=2e-5)
    assert props.center_of_mass[1] == pytest.approx(4.5, abs=1e-5)


def test_sketch_extrude_rejects_open_contour_without_committing() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        sketch_id=SKETCH_ID,
        frame=WorkPlaneFrame.xy(),
        entities=(LineEntity(OUTER_ID, (0.0, 0.0), (10.0, 0.0)),),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")

    with pytest.raises(GeometryBuildError, match="闭合轮廓") as failure:
        loaded.bus.execute("feature.extrude", _extrude_params(), confirmed_by="local", version=2)

    assert OUTER_ID in str(failure.value)
    assert "U/V" in str(failure.value) and "mm" in str(failure.value)
    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(0.0)


def test_sketch_extrude_builds_polygonal_outer_and_inner_loops() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        sketch_id=SKETCH_ID,
        frame=WorkPlaneFrame.xy(),
        entities=(
            RectangleEntity(OUTER_ID, (-10.0, -5.0), (10.0, 5.0)),
            PolylineEntity(
                INNER_ID,
                ((-2.0, -2.0), (2.0, -2.0), (2.0, 2.0), (-2.0, 2.0)),
                closed=True,
            ),
        ),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    loaded.bus.execute("feature.extrude", _extrude_params(3.0), confirmed_by="local", version=2)

    assert services.kernel.mass_properties().volume == pytest.approx(552.0, rel=1e-9)


def test_sketch_extrude_joins_directional_arcs_into_a_closed_profile() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        sketch_id=SKETCH_ID,
        frame=WorkPlaneFrame.xy(),
        entities=(
            ArcEntity(ARC_ID_A, (0.0, 0.0), 5.0, 0.0, 180.0),
            ArcEntity(ARC_ID_B, (0.0, 0.0), 5.0, 180.0, 180.0),
        ),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    loaded.bus.execute("feature.extrude", _extrude_params(2.0), confirmed_by="local", version=2)

    assert services.kernel.mass_properties().volume == pytest.approx(math.pi * 25.0 * 2.0, rel=2e-5)


def test_sketch_extrude_builds_multiple_outer_profiles_as_separate_bodies() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        sketch_id=SKETCH_ID,
        frame=WorkPlaneFrame.xy(),
        entities=(
            CircleEntity(OUTER_ID, (-10.0, 0.0), 4.0),
            CircleEntity(HOLE_ID, (10.0, 0.0), 4.0),
        ),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")

    loaded.bus.execute("feature.extrude", _extrude_params(), confirmed_by="local", version=2)

    properties = services.kernel.mass_properties()
    assert len(loaded.document.commands) == 2
    assert properties.solid_count == 2
    assert properties.volume == pytest.approx(2 * math.pi * 4.0**2 * 8.0)


def test_sketch_extrude_rejects_self_intersection_without_committing() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        sketch_id=SKETCH_ID,
        frame=WorkPlaneFrame.xy(),
        entities=(
            LineEntity(OUTER_ID, (-5.0, -5.0), (5.0, 5.0)),
            LineEntity(HOLE_ID, (5.0, 5.0), (-5.0, 5.0)),
            LineEntity(CONSTRUCTION_ID, (-5.0, 5.0), (5.0, -5.0)),
            LineEntity(REVOLVE_ID, (5.0, -5.0), (-5.0, -5.0)),
        ),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")

    with pytest.raises(GeometryBuildError, match="自相交") as failure:
        loaded.bus.execute("feature.extrude", _extrude_params(), confirmed_by="local", version=2)

    assert OUTER_ID in str(failure.value) and CONSTRUCTION_ID in str(failure.value)
    assert "U/V" in str(failure.value) and "mm" in str(failure.value)
    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(0.0)


def test_sketch_revolve_uses_workplane_geometry_and_version_two() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        sketch_id=SKETCH_ID,
        frame=WorkPlaneFrame.xz(),
        entities=(RectangleEntity(REVOLVE_ID, (2.0, -10.0), (4.0, 0.0)),),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    loaded.bus.execute(
        "feature.revolve",
        {
            "profile": {"type": "sketch", "sketch_id": SKETCH_ID},
            "axis": "Z",
            "angle_deg": 360.0,
            "mode": "new",
        },
        confirmed_by="local",
        version=2,
    )

    assert loaded.document.commands[-1].version == 2
    assert services.kernel.mass_properties().volume == pytest.approx(120.0 * math.pi, rel=2e-5)

    loaded.bus.undo()
    loaded.bus.execute(
        "feature.revolve",
        {
            "profile": {"type": "sketch", "sketch_id": SKETCH_ID},
            "axis": "Z",
            "angle_deg": 180.0,
            "mode": "new",
        },
        confirmed_by="local",
        version=2,
    )
    assert services.kernel.mass_properties().volume == pytest.approx(60.0 * math.pi, rel=2e-5)


def test_sketch_revolve_uses_offset_construction_axis_and_replays(tmp_path: Path) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    axis_id = "9c9c9c9c-9c9c-4c9c-8c9c-9c9c9c9c9c9c"
    sketch = Sketch(
        sketch_id=SKETCH_ID,
        frame=WorkPlaneFrame.xz(),
        entities=(
            RectangleEntity(REVOLVE_ID, (4.0, -10.0), (6.0, 0.0)),
            LineEntity(axis_id, (2.0, -10.0), (2.0, 0.0), construction=True),
        ),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    params = {
        "profile": {"type": "sketch", "sketch_id": SKETCH_ID},
        "axis_reference": {
            "type": "sketch_line",
            "sketch_id": SKETCH_ID,
            "entity_id": axis_id,
        },
        "angle_deg": 360.0,
        "mode": "new",
    }
    loaded.bus.execute("feature.revolve", params, confirmed_by="local", version=3)

    mass = services.kernel.mass_properties()
    assert loaded.document.commands[-1].version == 3
    assert mass.volume == pytest.approx(120.0 * math.pi, rel=2e-5)
    assert mass.center_of_mass == pytest.approx((2.0, 0.0, 5.0), abs=1e-6)

    archive = tmp_path / "offset-revolve.mc.json"
    save_document(loaded.document, archive)
    loaded.bus.undo()
    assert services.kernel.mass_properties().solid_count == 0
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(120.0 * math.pi, rel=2e-5)
    reopened = open_app_document(services, archive)
    assert services.kernel.mass_properties().center_of_mass == pytest.approx((2.0, 0.0, 5.0))
    assert reopened.document.commands[-1].version == 3


def test_sketch_revolve_rejects_nonconstruction_axis_without_commit() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    axis_id = "3b3b3b3b-3b3b-4b3b-8b3b-3b3b3b3b3b3b"
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            SKETCH_ID,
            WorkPlaneFrame.xz(),
            (
                RectangleEntity(REVOLVE_ID, (2.0, -10.0), (4.0, 0.0)),
                LineEntity(axis_id, (0.0, -10.0), (0.0, 0.0)),
            ),
        ).to_mapping(),
        confirmed_by="local",
    )

    with pytest.raises(ValidationError, match="construction line"):
        loaded.bus.execute(
            "feature.revolve",
            {
                "profile": {"type": "sketch", "sketch_id": SKETCH_ID},
                "axis_reference": {
                    "type": "sketch_line",
                    "sketch_id": SKETCH_ID,
                    "entity_id": axis_id,
                },
                "angle_deg": 360.0,
                "mode": "new",
            },
            confirmed_by="local",
            version=3,
        )

    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().solid_count == 0


def test_sketch_revolve_axis_reference_must_belong_to_profile_sketch() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    axis_sketch_id = "2a2a2a2a-2a2a-4a2a-8a2a-2a2a2a2a2a2a"
    axis_id = "3b3b3b3b-3b3b-4b3b-8b3b-3b3b3b3b3b3b"
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            SKETCH_ID,
            WorkPlaneFrame.xz(),
            (RectangleEntity(REVOLVE_ID, (4.0, -10.0), (6.0, 0.0)),),
        ).to_mapping(),
        confirmed_by="local",
    )
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            axis_sketch_id,
            WorkPlaneFrame.xz(),
            (LineEntity(axis_id, (2.0, -10.0), (2.0, 0.0), construction=True),),
        ).to_mapping(),
        confirmed_by="local",
    )

    with pytest.raises(ValidationError, match="same sketch"):
        loaded.bus.execute(
            "feature.revolve",
            {
                "profile": {"type": "sketch", "sketch_id": SKETCH_ID},
                "axis_reference": {
                    "type": "sketch_line",
                    "sketch_id": axis_sketch_id,
                    "entity_id": axis_id,
                },
                "angle_deg": 360.0,
                "mode": "new",
            },
            confirmed_by="local",
            version=3,
        )

    assert len(loaded.document.commands) == 2
    assert services.kernel.mass_properties().solid_count == 0


@pytest.mark.parametrize("frame", [WorkPlaneFrame.xy(), WorkPlaneFrame.xz(), WorkPlaneFrame.yz()])
def test_profile_error_coordinates_are_local_to_the_authored_plane(frame: WorkPlaneFrame) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(SKETCH_ID, frame, (LineEntity(OUTER_ID, (12.0, 8.0), (20.0, 8.0)),))
    loaded.bus.execute("sketch.create", sketch.to_mapping(), "test")
    with pytest.raises(GeometryBuildError) as failure:
        loaded.bus.execute("feature.extrude", _extrude_params(), "test")
    assert "(12, 8)" in str(failure.value)
    assert "U/V (mm)" in str(failure.value)
    assert OUTER_ID in str(failure.value)
    assert len(loaded.document.commands) == 1


def test_profile_degenerate_short_edge_identifies_its_source() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (
            LineEntity(OUTER_ID, (0.0, 0.0), (0.000001, 0.0)),
            RectangleEntity(HOLE_ID, (10.0, 10.0), (2010.0, 2010.0)),
        ),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), "test")
    with pytest.raises(GeometryBuildError, match="退化边") as failure:
        loaded.bus.execute("feature.extrude", _extrude_params(), "test")
    assert OUTER_ID in str(failure.value)
    assert HOLE_ID not in str(failure.value)
    assert "U/V (mm)" in str(failure.value)
    assert len(loaded.document.commands) == 1


def test_crossing_loops_identify_both_source_entities() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (
            CircleEntity(OUTER_ID, (0.0, 0.0), 10.0),
            CircleEntity(HOLE_ID, (10.0, 0.0), 10.0),
        ),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), "test")
    with pytest.raises(GeometryBuildError, match="相交或相切") as failure:
        loaded.bus.execute("feature.extrude", _extrude_params(), "test")
    assert OUTER_ID in str(failure.value) and HOLE_ID in str(failure.value)
    assert "精确边界接触位置" in str(failure.value)
    assert len(loaded.document.commands) == 1


@pytest.mark.parametrize("frame", [WorkPlaneFrame.xy(), WorkPlaneFrame.xz(), WorkPlaneFrame.yz()])
@pytest.mark.parametrize("arc_outer", [False, True])
def test_near_nested_curves_use_exact_boundaries(frame: WorkPlaneFrame, arc_outer: bool) -> None:
    from mycad.geom.sketch_profiles import make_sketch_faces

    angle = math.radians(360.0 / 256.0)
    center = (89.99 * math.cos(angle), 89.99 * math.sin(angle))
    outer = (
        (
            ArcEntity(ARC_ID_A, (0.0, 0.0), 100.0, 0.0, 180.0),
            ArcEntity(ARC_ID_B, (0.0, 0.0), 100.0, 180.0, 180.0),
        )
        if arc_outer
        else (CircleEntity(OUTER_ID, (0.0, 0.0), 100.0),)
    )
    sketch = Sketch(
        SKETCH_ID,
        frame,
        (*outer, CircleEntity(HOLE_ID, center, 10.0), CircleEntity(INNER_ID, center, 1.0)),
    )
    faces = make_sketch_faces(sketch)
    assert len(faces) == 2
    assert all(face.is_valid for face in faces)
    assert sorted(face.area for face in faces) == pytest.approx([math.pi, 9900 * math.pi])


@pytest.mark.parametrize("center_distance", [90.0, 90.001, 110.0])
def test_true_curved_contour_contact_is_rejected(center_distance: float) -> None:
    from mycad.geom.sketch_profiles import make_sketch_faces

    angle = math.radians(360.0 / 256.0)
    center = (center_distance * math.cos(angle), center_distance * math.sin(angle))
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (
            CircleEntity(OUTER_ID, (0.0, 0.0), 100.0),
            CircleEntity(HOLE_ID, center, 10.0),
        ),
    )
    with pytest.raises(GeometryBuildError, match="相交或相切") as error:
        make_sketch_faces(sketch)
    assert OUTER_ID in str(error.value) and HOLE_ID in str(error.value)
    assert "U/V (mm)" in str(error.value)
