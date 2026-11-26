# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Create a graphical-compatibility DXF for external renderer inspection."""
from pathlib import Path
from uuid import uuid4
from mycad import app
from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference, FeatureControlFrame, ToleranceRow
from mycad.core.sketch import LineEntity, RectangleEntity, Sketch, WorkPlaneFrame
from mycad.formats.dxf_preview import prepare_dxf_output_preview

out = Path(__file__).resolve().parent
services = app.build_app(discoverers=())
loaded = app.new_workspace_document(services, kind="sketch")
entities = (LineEntity(uuid4().hex, (0, 0), (40, 0)), RectangleEntity(uuid4().hex, (-10, -20), (60, 30)))
app.commit_new_sketch(services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities), session_identity=0)
datum = DatumIdentifier(uuid4().hex, "A", (0, -10), (0, 0))
frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2, True, "M", (DatumReference("A", datum.datum_id),)),), (10, 15))
loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]}, "local")
preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
preview.write(out / "compatibility.dxf")
(out / "mycad-preview.svg").write_bytes(preview.svg_bytes)
print(preview.report)
