# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared drawing layers replay through Bus without disabling constraints."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from mycad.app import build_app, new_document, open_app_document
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import DEFAULT_DIM_LAYER, SketchLayer, SketchLayerTable


def annotated() -> Sketch:
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        30,
        "mm",
        layer_name="DIM",
        position_mm=(15, -10),
    )
    return Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))


def test_shared_layers_bus_undo_and_archive(tmp_path: Path) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    sketches = (annotated(), annotated())
    for sketch in sketches:
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    table = SketchLayerTable().add(replace(DEFAULT_DIM_LAYER, visible=False, frozen=True))
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": table.to_mapping(), "dimension_layer": "DIM"},
        confirmed_by="local",
    )
    assert services.kernel.drawing_layers.get("DIM").frozen
    assert all(not s.layers.get("DIM").visible for s in services.kernel.sketches)
    assert all(s.constraints[0].driving for s in services.kernel.sketches)
    assert all(not s.dimensions for s in services.kernel.sketch_display_data())
    loaded.bus.undo()
    assert all(s.layers.get("DIM").displayed for s in services.kernel.sketches)
    loaded.bus.redo()
    path = tmp_path / "layers.mc.json"
    save_document(loaded.document, path)
    reopened = open_app_document(services, path)
    assert reopened.document.document_type == "drawing2d"
    assert services.kernel.dimension_layer == "DIM"
    assert services.kernel.drawing_layers == table


def test_hidden_geometry_does_not_hide_independent_dim() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = annotated()
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    table = sketch.layers.replace(replace(sketch.layers.get("0"), visible=False))
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": table.to_mapping(), "dimension_layer": "DIM"},
        confirmed_by="local",
    )
    display = services.kernel.sketch_display_data()[0]
    assert not display.curves
    assert len(display.dimensions) == 1
    assert services.kernel.sketches[0].entities == sketch.entities


def test_bulk_move_legacy_dimensions_is_atomic() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = annotated()
    legacy = replace(sketch, constraints=(replace(sketch.constraints[0], layer_name=None),))
    loaded.bus.execute("sketch.create", legacy.to_mapping(version=3), confirmed_by="local")
    params = {
        "layers": legacy.layers.to_mapping(),
        "dimension_layer": "DIM",
        "assignments": [
            {
                "sketch_id": sketch.sketch_id,
                "constraint_ids": [sketch.constraints[0].constraint_id],
                "layer_name": "DIM",
            }
        ],
    }
    loaded.bus.execute("drawing.layers.set", params, confirmed_by="local")
    assert services.kernel.sketches[0].constraints[0].layer_name == "DIM"
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints[0].layer_name is None
    params["assignments"] = [
        {"sketch_id": sketch.sketch_id, "constraint_ids": [uuid4().hex], "layer_name": "DIM"}
    ]
    before = tuple(loaded.document.commands)
    with pytest.raises(Exception, match="dimension|标注"):
        loaded.bus.execute("drawing.layers.set", params, confirmed_by="local")
    assert tuple(loaded.document.commands) == before


def test_empty_drawing_layer_preferences_survive_open_into_fresh_state(tmp_path: Path) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    table = SketchLayerTable().add(DEFAULT_DIM_LAYER).add(SketchLayer("notes", frozen=True))
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": table.to_mapping(), "dimension_layer": "notes"},
        confirmed_by="local",
    )
    path = tmp_path / "empty-layers.my2d"
    save_document(loaded.document, path)
    services.kernel.reset()
    open_app_document(services, path)
    assert services.kernel.dimension_layer == "notes"
    assert services.kernel.drawing_layers.get("notes").frozen


def test_dimension_edit_after_later_annotation_layer_assignment() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = annotated()
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": sketch.layers.to_mapping(), "dimension_layer": "DIM"},
        confirmed_by="local",
    )
    table = sketch.layers.add(SketchLayer("notes"))
    loaded.bus.execute(
        "drawing.layers.set",
        {
            "layers": table.to_mapping(),
            "dimension_layer": "notes",
            "assignments": [
                {
                    "sketch_id": sketch.sketch_id,
                    "constraint_ids": [sketch.constraints[0].constraint_id],
                    "layer_name": "notes",
                }
            ],
        },
        confirmed_by="local",
    )
    current = services.kernel.sketches[0]
    revised = replace(current.constraints[0], value=40)
    preview = services.kernel.preview_sketch_constraint_update(current, revised)
    assert preview.status == "success", preview.message
    loaded.bus.execute(
        "sketch.constraint.update", preview.command_params(current, revised), confirmed_by="local"
    )
    assert services.kernel.sketches[0].constraints[0].value == 40
    assert services.kernel.sketches[0].constraints[0].layer_name == "notes"
    assert services.kernel.drawing_layers == table
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints[0].value == 30
    loaded.bus.redo()
    assert services.kernel.sketches[0].constraints[0].value == 40
