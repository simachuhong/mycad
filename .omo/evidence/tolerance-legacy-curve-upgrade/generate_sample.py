# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Generate a legacy-curve identity-upgrade manual test document."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from mycad import app
from mycad.core.geometric_tolerance import (
    DatumAttachment,
    DatumIdentifier,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.core.persistence import save_document
from mycad.core.sketch import PolylineEntity, Sketch, SplineEntity, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference

OUT = Path(__file__).resolve().parent


def identifier(name: str) -> str:
    return uuid5(NAMESPACE_URL, f"mycad-legacy-curve-upgrade:{name}").hex


services = app.build_app(discoverers=())
loaded = app.new_workspace_document(services, kind="sketch")
polyline = PolylineEntity(identifier("polyline"), ((0, 0), (30, 0), (30, 15)))
spline = SplineEntity(identifier("spline"), ((0, -20), (10, -12), (20, -28), (30, -20)))
sketch = Sketch(identifier("sketch"), WorkPlaneFrame.xy(), (polyline, spline))
app.commit_new_sketch(services, loaded, sketch, session_identity=0)
datum = DatumIdentifier(
    identifier("datum"),
    "A",
    (38, 10),
    (30, 0),
    attachment=DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(polyline.entity_id, "vertex", 1)
    ),
)
frame = FeatureControlFrame(
    identifier("frame"),
    (ToleranceRow("flatness", 0.1, 2),),
    (0, 20),
    leader_target_mm=(15, 0),
    leader_attachment=DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(polyline.entity_id, "segment", 0), 0.5, 2
    ),
)
loaded.bus.execute(
    "drawing.tolerance.batch",
    {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
    "local",
)
path = OUT / "legacy-curves.my2d"
save_document(loaded.document, path)
restored = app.build_app(discoverers=())
app.open_app_document(restored, path)
assert restored.kernel.sketches == (sketch,)
assert restored.kernel.drawing_datum_identifiers == (datum,)
assert restored.kernel.drawing_tolerance_frames == (frame,)
assert not polyline.point_ids and not spline.point_ids
manifest = {
    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    "sketch_id": sketch.sketch_id,
    "polyline_id": polyline.entity_id,
    "spline_id": spline.entity_id,
    "datum_id": datum.datum_id,
    "frame_id": frame.frame_id,
}
(OUT / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(manifest, ensure_ascii=False))
