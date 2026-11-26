# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Ellipses survive command replay and native document persistence."""

from pathlib import Path
from uuid import uuid4

from mycad import app
from mycad.core.persistence import save_document
from mycad.core.sketch import EllipseEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_ellipse_create_save_reopen_undo_redo(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    ellipse = EllipseEntity(uuid4().hex, (2, 3), 6, 3, 35, 15, -100)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (ellipse,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    display = services.kernel.sketch_display_data()
    assert len(display) == 1
    assert any(curve.entity_id == ellipse.entity_id for curve in display[0].curves)
    assert services.kernel.snap_anchor_data()
    target = tmp_path / "ellipse.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    opened = app.open_app_document(reopened, target)
    assert reopened.kernel.sketches == (sketch,)
    opened.bus.undo()
    assert reopened.kernel.sketches == ()
    opened.bus.redo()
    assert reopened.kernel.sketches == (sketch,)


def test_unrelated_constraint_can_coexist_with_ellipse() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    ellipse = EllipseEntity(uuid4().hex, (2, 3), 6, 3)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    relation = SketchConstraint(
        uuid4().hex,
        "horizontal",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        source="inferred",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (ellipse, line), (relation,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    assert services.kernel.sketches == (sketch,)
