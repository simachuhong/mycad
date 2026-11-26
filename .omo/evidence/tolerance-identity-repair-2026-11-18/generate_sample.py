# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Generate a legacy annotation identity collision for manual repair acceptance."""

from dataclasses import replace
from pathlib import Path

from mycad import app
from mycad.core.detached_dimension import DetachedDimension
from mycad.core.geometric_tolerance import (
    DatumIdentifier,
    DatumReference,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.core.persistence import save_document
from mycad.core.sketch_layers import SketchLayer

IDENTITY = "ab" * 16
destination = Path(__file__).resolve().parent / "legacy-identity-conflict.my2d"
services = app.build_app(discoverers=())
loaded = app.new_workspace_document(services, kind="sketch")
layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
loaded.bus.execute(
    "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
)
datum = DatumIdentifier(IDENTITY, "A", (0, 0), (0, -5))
frame = FeatureControlFrame(
    IDENTITY,
    (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", IDENTITY),)),),
    (10, 5),
    layer_name="GDT",
)
dimension = DetachedDimension(IDENTITY, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
loaded.bus.execute(
    "drawing.tolerance.batch",
    {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    "local",
    version=6,
)
loaded.bus.execute(
    "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local", version=5
)
save_document(loaded.document, destination)
print(destination)
locked = replace(
    layers,
    layers=tuple(
        replace(layer, locked=True) if layer.name == "GDT" else layer for layer in layers.layers
    ),
)
loaded.bus.execute(
    "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
)
locked_destination = destination.with_name("legacy-identity-conflict-locked.my2d")
save_document(loaded.document, locked_destination)
print(locked_destination)
