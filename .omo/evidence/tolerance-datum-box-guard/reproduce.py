from dataclasses import replace
from math import sqrt
from uuid import uuid4

from mycad import app
from mycad.core.drawing_text import TextStyle
from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
from mycad.core.geometric_tolerance_geometry import _leader_crosses_arrow, datum_leader_path
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.formats.dxf_datum import datum_box_dimensions

services = app.build_app(discoverers=())
loaded = app.new_workspace_document(services, kind="sketch")
old_target = (-7.0, -3.0 + sqrt(272))
line = LineEntity(uuid4().hex, old_target, (13.0, old_target[1]))
sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
app.commit_new_sketch(services, loaded, sketch, session_identity=0)
attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
datum = DatumIdentifier(
    uuid4().hex, "A", (0, 0), old_target, attachment=attachment,
    leader_offsets=((8, -9), (8, -3), (-7, -3)), leader_auto_normal=True,
    leader_auto_route=True, route_avoid_crossing=True, route_track_target=True,
    route_algorithm_version=2, layout_mode="shared",
)
loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=25)
state = replace(sketch, entities=(replace(line, start_mm=(9, 1), end_mm=(13, -15)),)).to_state_mapping()
loaded.bus.execute(
    "drawing.sketch.revise",
    {"revisions": [{"sketch_id": sketch.sketch_id, "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"], "constraints": state["constraints"]}]},
    "local", version=56,
)
result = services.kernel.drawing_datum_identifiers[0]
width, height = datum_box_dimensions(result.label, TextStyle())
path = datum_leader_path((0, 0, width, -height), result.target_mm, result.leader_offsets)
normal = result.leader_offsets[-1]
intersection = _leader_crosses_arrow(path[0], path[1], result.target_mm, normal)
print(f"box={width:.6f}x{height:.6f} target={result.target_mm} path={path}")
print(f"visible_first_segment_crosses_arrow={intersection}")
if not intersection:
    raise SystemExit("This diagnostic no longer reproduces the defect; re-evaluate its expected result.")
