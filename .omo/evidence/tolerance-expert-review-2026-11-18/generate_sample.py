# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Generate structural samples for expert review, not normative examples."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from mycad import app
from mycad.core.geometric_tolerance import (
    CHARACTERISTICS,
    DatumIdentifier,
    DatumReference,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.core.persistence import save_document
from mycad.formats.dxf_preview import prepare_dxf_output_preview
from mycad.formats.providers.dxf_provider import read_sketch_dxf

OUT = Path(__file__).resolve().parent

def identifier(name: str) -> str:
    return uuid5(NAMESPACE_URL, f"mycad-tolerance-review:{name}").hex

services = app.build_app(discoverers=())
loaded = app.new_workspace_document(services, kind="sketch")
frames = []
items = []
for index, characteristic in enumerate(CHARACTERISTICS):
    point = ((index % 3) * 55.0, 100.0 - (index // 3) * 15.0)
    frame = FeatureControlFrame(identifier(characteristic), (ToleranceRow(characteristic, 0.12, 2),), point)
    frames.append(frame)
    items.append({"index": index + 1, "characteristic": characteristic, "position_mm": point})

datums = [DatumIdentifier(identifier(f"datum-{letter}"), letter, (x, 5), (x, 0)) for x, letter in ((0, "A"), (30, "B"), (60, "C"))]
rows = (
    ToleranceRow("position", 0.12, 2, True, "M", (DatumReference("A", datums[0].datum_id), DatumReference("B", datums[1].datum_id, "L"), DatumReference("C", datums[2].datum_id))),
    ToleranceRow("parallelism", 0.08, 2, False, "L", (DatumReference("A", datums[0].datum_id),)),
)
frames.append(FeatureControlFrame(identifier("multiline"), rows, (0, 20)))
loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping() for frame in frames], "add_datums": [datum.to_mapping() for datum in datums]}, "local")
save_document(loaded.document, OUT / "review-sample.my2d")
preview = prepare_dxf_output_preview(services.kernel)
(OUT / "review-sample.dxf").write_bytes(preview.dxf_bytes)
(OUT / "review-sample.svg").write_bytes(preview.svg_bytes)
imported = read_sketch_dxf(OUT / "review-sample.dxf")
assert len(imported.tolerance_frames) == len(frames)
assert len(imported.datum_identifiers) == len(datums)
assert [frame.rows for frame in imported.tolerance_frames] == [frame.rows for frame in frames]
files = ("review-sample.my2d", "review-sample.dxf", "review-sample.svg")
manifest = {
    "purpose": "Structural display samples only; no GB/ISO validity is asserted.",
    "symbol_order": items,
    "multiline_position_mm": [0, 20],
    "multiline_rows": [row.to_mapping() for row in rows],
    "warning": list(preview.report.warnings),
    "sha256": {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() for name in files},
}
(OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"frames={len(frames)} datums={len(datums)}")
print("warnings:", list(preview.report.warnings))
