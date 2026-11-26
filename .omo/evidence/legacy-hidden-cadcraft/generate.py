from pathlib import Path

from mycad.core.geometric_tolerance import DatumAttachment, FeatureControlFrame, ToleranceRow
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.formats.providers.dxf_provider import write_sketches_dxf

directory = Path(__file__).parent

for name, origin, target, vertices, line_ends, anchor in (
    ("route", (20, 20), (0, 0), ((8, -3), (-20, -15)), ((-5, 0), (5, 0)), (2.5, -6)),
    ("normal", (0, 6), (2, -2), ((2, -3),), ((-3, -2), (7, -2)), (5.2, -6)),
):
    line = LineEntity("a" * 32, *line_ends)
    sketch = Sketch("b" * 32, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5)
    frame = FeatureControlFrame(
        "c" * 32,
        (ToleranceRow("position", 0.1, 2),),
        origin,
        leader_target_mm=target,
        leader_offsets=vertices,
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    write_sketches_dxf(
        (sketch,),
        directory / f"{name}-source.dxf",
        tolerance_frames=(frame,),
        legacy_frame_anchors={frame.frame_id: anchor},
        legacy_frame_skipped_vertices={frame.frame_id: 1},
        legacy_frame_bounds={frame.frame_id: (0, 0, 20, 6)},
    )
