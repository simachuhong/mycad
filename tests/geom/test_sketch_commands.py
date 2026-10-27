# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Sketch creation is a replayable Bus command with durable entity identity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mycad.app import build_app, new_document, open_app_document
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import (
    ArcEntity,
    LineEntity,
    Sketch,
    SketchSupportFace,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.geom.kernel import BuildKernel

SKETCH_ID = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
ENTITY_ID = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"


def _sketch() -> Sketch:
    return Sketch(
        sketch_id=SKETCH_ID,
        frame=WorkPlaneFrame.xz(),
        entities=(LineEntity(ENTITY_ID, (2.0, 3.0), (12.0, 3.0)),),
    )


@pytest.mark.parametrize("gap", [0.0, 0.1])
def test_initial_inferred_coincidence_is_validated_and_replayed(tmp_path: Path, gap: float) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    second_id = "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c"
    relation = SketchConstraint(
        "3d3d3d3d-3d3d-4d3d-8d3d-3d3d3d3d3d3d",
        "coincident",
        (SketchGeometryReference(ENTITY_ID, "end"), SketchGeometryReference(second_id, "start")),
        source="inferred",
    )
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (
            LineEntity(ENTITY_ID, (0.0, 0.0), (10.0, 0.0)),
            LineEntity(second_id, (10.0 + gap, 0.0), (10.0 + gap, 10.0)),
        ),
        (relation,),
    )
    if gap:
        with pytest.raises(ValidationError, match="does not match geometry"):
            loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "test")
        assert not loaded.document.commands
        assert not services.kernel.sketches
        return
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "test")
    loaded.bus.undo()
    loaded.bus.redo()
    path = tmp_path / "coincident.mc.json"
    save_document(loaded.document, path)
    open_app_document(services, path)
    assert services.kernel.sketches == (sketch,)


def test_sketch_create_replays_undo_redo_and_preserves_entity_identity() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = _sketch()

    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")

    assert loaded.document.commands[0].id == "sketch.create"
    assert services.kernel.sketches == (sketch,)
    loaded.bus.undo()
    assert services.kernel.sketches == ()
    loaded.bus.redo()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.sketches[0].entities[0].entity_id == ENTITY_ID


def test_sketch_archive_uses_v2_and_reopens_the_same_sketch(tmp_path: Path) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = _sketch()
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    archive = tmp_path / "profile.mc.json"

    save_document(loaded.document, archive)

    data = json.loads(archive.read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert set(data) == {"format", "version", "metadata", "commands", "named_groups", "provenance"}
    command = data["commands"][0]
    assert command["id"] == "sketch.create"
    assert command["params"]["sketch_id"] == SKETCH_ID
    assert data["provenance"]["units"] == {"length": "mm", "angle": "deg"}

    reopened = open_app_document(services, archive)
    assert reopened.document.archive_version == 2
    assert services.kernel.sketches == (sketch,)
    assert reopened.document.commands[0].timestamp_utc == loaded.document.commands[0].timestamp_utc


def test_clockwise_arc_projection_keeps_curve_direction() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        sketch_id=SKETCH_ID,
        frame=WorkPlaneFrame.xy(),
        entities=(ArcEntity(ENTITY_ID, (0.0, 0.0), 10.0, 0.0, -90.0),),
    )

    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")

    points = services.kernel.sketch_display_data()[0].curves[0].points
    assert points[0] == pytest.approx((10.0, 0.0, 0.0))
    assert points[-1] == pytest.approx((0.0, -10.0, 0.0))
    assert all(point[1] <= 1e-9 for point in points)


def test_sketch_viewport_uses_layer_style_and_omits_hidden_entities() -> None:
    outline = SketchLayer("OUTLINE", color_rgb=(210, 40, 55), linetype="DASHED")
    hidden = SketchLayer("HIDDEN", visible=False)
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (
            LineEntity(
                ENTITY_ID,
                (0.0, 0.0),
                (10.0, 0.0),
                layer_name="OUTLINE",
            ),
            LineEntity(
                "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c",
                (0.0, 5.0),
                (10.0, 5.0),
                layer_name="HIDDEN",
            ),
        ),
        layers=SketchLayerTable().add(outline).add(hidden),
    )
    kernel = BuildKernel()

    kernel.apply("sketch.create", sketch.to_mapping())
    curves = kernel.sketch_display_data()[0].curves

    assert len(curves) == 1
    assert curves[0].entity_id == ENTITY_ID
    assert curves[0].layer == outline


def test_sketch_display_data_includes_formatted_dimension_overlay() -> None:
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(ENTITY_ID, (0.0, 0.0), (10.0, 0.0)),),
        constraints=(
            SketchConstraint(
                "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c",
                "length",
                (SketchGeometryReference(ENTITY_ID, "geometry"),),
                value=10.0,
                unit="mm",
                driving=False,
                precision=3,
                scale=2.0,
            ),
        ),
    )
    kernel = BuildKernel()

    kernel.apply("sketch.create", sketch.to_mapping(version=3))
    displayed = kernel.sketch_display_data()[0]

    assert len(displayed.dimensions) == 1
    assert displayed.dimensions[0].text == "10.000 mm"
    assert displayed.dimensions[0].position == pytest.approx((5.0, 10.0, 0.0))


def test_sketch_create_accepts_geometrically_satisfied_inferred_relation() -> None:
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(ENTITY_ID, (0.0, 0.0), (10.0, 0.0)),),
        constraints=(
            SketchConstraint(
                "3d3d3d3d-3d3d-4d3d-8d3d-3d3d3d3d3d3d",
                "horizontal",
                (SketchGeometryReference(ENTITY_ID, "geometry"),),
                source="inferred",
            ),
        ),
    )
    kernel = BuildKernel()

    kernel.apply("sketch.create", sketch.to_mapping(version=3))

    assert kernel.sketches == (sketch,)


def test_sketch_create_rejects_inferred_relation_that_does_not_match_geometry() -> None:
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(ENTITY_ID, (0.0, 0.0), (10.0, 2.0)),),
        constraints=(
            SketchConstraint(
                "3d3d3d3d-3d3d-4d3d-8d3d-3d3d3d3d3d3d",
                "horizontal",
                (SketchGeometryReference(ENTITY_ID, "geometry"),),
                source="inferred",
            ),
        ),
    )
    kernel = BuildKernel()

    with pytest.raises(ValidationError, match="horizontal"):
        kernel.apply("sketch.create", sketch.to_mapping(version=3))


def test_face_attached_sketch_replays_against_the_selected_planar_face(
    tmp_path: Path,
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute(
        "feature.box",
        {"size_x": 40.0, "size_y": 30.0, "size_z": 8.0},
        confirmed_by="local",
    )
    face = services.kernel.viewport_data()[-1].faces[0]
    descriptor = services.kernel.interactive_face_selector(face.topology_id)
    face_frame = services.kernel.interactive_face_frame(face.topology_id)
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.from_planar_face(face_frame.origin, face_frame.normal),
        (LineEntity(ENTITY_ID, (0.0, 0.0), (10.0, 0.0)),),
        support_face=SketchSupportFace.from_mapping(descriptor),
    )

    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")

    attached = services.kernel.sketches[-1]
    assert attached.support_face == sketch.support_face
    assert attached.frame == sketch.frame
    loaded.bus.undo()
    assert services.kernel.sketches == ()
    loaded.bus.redo()
    assert services.kernel.sketches == (attached,)
    archive = tmp_path / "face-attached.mc.json"
    save_document(loaded.document, archive)

    reopened = open_app_document(services, archive)

    assert reopened.document.commands[-1].id == "sketch.create"
    assert services.kernel.sketches == (attached,)


def test_dimension_annotated_sketch_v3_replays_and_survives_archive_round_trip(
    tmp_path: Path,
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(ENTITY_ID, (0.0, 0.0), (10.0, 0.0)),),
        constraints=(
            SketchConstraint(
                "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c",
                "length",
                (SketchGeometryReference(ENTITY_ID, "geometry"),),
                value=10.0,
                unit="mm",
                driving=False,
                precision=3,
                scale=2.0,
            ),
        ),
    )

    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")

    assert loaded.document.commands[0].version == 3
    assert services.kernel.sketches == (sketch,)
    loaded.bus.undo()
    assert services.kernel.sketches == ()
    loaded.bus.redo()
    assert services.kernel.sketches == (sketch,)
    archive = tmp_path / "dimensioned-sketch.mc.json"
    save_document(loaded.document, archive)

    reopened = open_app_document(services, archive)

    assert reopened.document.commands[0].version == 3
    assert services.kernel.sketches == (sketch,)


def test_sketch_create_rejects_dimensions_that_do_not_match_geometry() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(ENTITY_ID, (0.0, 0.0), (10.0, 0.0)),),
        constraints=(
            SketchConstraint(
                "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c",
                "length",
                (SketchGeometryReference(ENTITY_ID, "geometry"),),
                value=11.0,
                unit="mm",
                driving=False,
            ),
        ),
    )

    with pytest.raises(ValidationError, match="does not match its geometry"):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")

    assert loaded.document.commands == ()
    assert services.kernel.sketches == ()
