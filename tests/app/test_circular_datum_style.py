# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Circular datum styles use replayable versioned commands."""

from dataclasses import replace
from pathlib import Path

import pytest

from mycad import app
from mycad.core.exceptions import ValidationError
from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference


def test_circular_datum_style_version_undo_and_reopen(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier("9" * 32, "A", (10, 10), (0, 0), symbol_style="circle")
    params = {"add_datums": [datum.to_mapping()]}
    with pytest.raises(ValidationError, match="基准标识样式"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=29)
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=30)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == ()
    loaded.bus.redo_operation()
    path = tmp_path / "circular-datum.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)


def test_baseline_rotation_updates_bar_and_replays(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity("a" * 32, (0, 0), (40, 0))
    sketch = Sketch("b" * 32, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        "c" * 32,
        "A",
        (40, 30),
        (20, 0),
        symbol_style="circle",
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
        ),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=30
    )
    assert services.kernel.drawing_datum_identifiers[0].bar_direction == pytest.approx((1, 0))
    explicit = replace(datum, bar_direction=(1, 0)).to_mapping()
    with pytest.raises(ValidationError, match="短线方向"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"update_datums": [explicit]}, "local", version=30
        )
    changed = replace(sketch, entities=(replace(line, end_mm=(0, 40)),))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    assert services.kernel.drawing_datum_identifiers[0].bar_direction == pytest.approx((0, 1))
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers[0].bar_direction == pytest.approx((1, 0))
    loaded.bus.redo_operation()
    path = tmp_path / "rotated-datum.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers[0].bar_direction == pytest.approx((0, 1))
