# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Generate a two-style tolerance comparison for external visual review."""

from pathlib import Path
from uuid import uuid4

from mycad import app
from mycad.core.drawing_text import TextStyle, TextStyleTable
from mycad.core.geometric_tolerance import DatumReference, FeatureControlFrame, ToleranceRow
from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame
from mycad.formats.dxf_preview import prepare_dxf_output_preview
from mycad.formats.providers.dxf_provider import DXF_PROVIDER

out = Path(__file__).resolve().parent
services = app.build_app(discoverers=())
loaded = app.new_workspace_document(services, kind="sketch")
style = TextStyle("review", "Review Wide", "DejaVu Sans", height_mm=7, width_factor=3)
loaded.bus.execute("drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local")
border = RectangleEntity(uuid4().hex, (-10, -20), (160, 70))
app.commit_new_sketch(services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (border,)), session_identity=0)
row = ToleranceRow("position", 0.05, 2, True, "M", (DatumReference("A", modifier="L"),))
frames = (
    FeatureControlFrame(uuid4().hex, (row,), (0, 45)),
    FeatureControlFrame(uuid4().hex, (row,), (0, 20), text_style_id="review"),
)
loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [f.to_mapping() for f in frames]}, "local")
print(DXF_PROVIDER.write(services.kernel, out / "native.dxf"))
preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
preview.write(out / "graphics.dxf")
(out / "mycad-preview.svg").write_bytes(preview.svg_bytes)
print(preview.report)
