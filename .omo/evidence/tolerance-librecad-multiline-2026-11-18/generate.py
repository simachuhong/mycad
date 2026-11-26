# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Convert the existing review document to a graphical compatibility sample."""
from pathlib import Path
from uuid import uuid4
from mycad import app
from mycad.formats.dxf_preview import prepare_dxf_output_preview
from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame

out = Path(__file__).resolve().parent
source = out.parent / "tolerance-expert-review-2026-11-18" / "review-sample.my2d"
services = app.build_app(discoverers=())
loaded = app.open_app_document(services, source)
border = RectangleEntity(uuid4().hex, (-15, -15), (165, 115))
app.commit_new_sketch(services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (border,)), session_identity=0)
preview = prepare_dxf_output_preview(services.kernel, tolerance_graphics=True)
preview.write(out / "multiline.dxf")
(out / "mycad-preview.svg").write_bytes(preview.svg_bytes)
print(preview.report)
