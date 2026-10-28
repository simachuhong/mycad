# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Sketch paper sources replay without a solid and keep old command contracts."""

from pathlib import Path
from uuid import uuid4

import pytest

from mycad.app import build_app, new_document, open_app_document
from mycad.core.exceptions import MycadError
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame


def test_sketch_paper_roundtrip_undo_and_reference(tmp_path: Path) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    sketch = Sketch(str(uuid4()), WorkPlaneFrame.xy(), (LineEntity(str(uuid4()), (0, 0), (40, 0)),))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3))
    original = loaded.document.commands[0]
    sheet, view = str(uuid4()), str(uuid4())
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": sheet})
    loaded.bus.execute(
        "drawing.view.create",
        {
            "view_id": view,
            "sheet_id": sheet,
            "source": {"kind": "sketch", "sketch_id": sketch.sketch_id},
            "anchor_mm": [80, 100],
            "scale": 0.5,
        },
    )
    loaded.bus.execute(
        "drawing.annotation.create",
        {
            "annotation_id": str(uuid4()),
            "view_id": view,
            "kind": "aligned",
            "references": [
                {
                    "kind": "sketch_entity",
                    "sketch_id": sketch.sketch_id,
                    "entity_id": sketch.entities[0].entity_id,
                }
            ],
            "position_mm": [80, 120],
        },
    )
    before = services.kernel.drawing_state
    path = tmp_path / "flat.my2d"
    save_document(loaded.document, path)
    reopened = open_app_document(services, path)
    assert services.kernel.drawing_state == before
    assert reopened.document.commands[0] == original
    reopened.bus.undo()
    assert not services.kernel.drawing_state.annotations
    reopened.bus.undo()
    assert not services.kernel.drawing_state.views
    reopened.bus.redo()
    reopened.bus.redo()
    assert services.kernel.drawing_state == before


def test_missing_sources_and_old_version_rejected_atomically() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    sheet = str(uuid4())
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": sheet})
    for source in ({"kind": "current_part"}, {"kind": "sketch", "sketch_id": str(uuid4())}):
        params = {"view_id": str(uuid4()), "sheet_id": sheet, "source": source}
        with pytest.raises(MycadError):
            loaded.bus.execute("drawing.view.create", params)
        with pytest.raises(MycadError):
            loaded.bus.execute("drawing.view.create", params, version=1)
    assert len(loaded.document.commands) == 1
    assert not services.kernel.drawing_state.views
    with pytest.raises(MycadError):
        loaded.bus.execute("feature.box", {"size_x": 1, "size_y": 2, "size_z": 3})
