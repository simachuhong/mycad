# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Collection operations preserve datum pointer styles."""

from uuid import uuid4

import pytest

from mycad import app
from mycad.core.drawing_collection_clipboard import (
    capture_collection_clipboard,
    prepare_collection_paste,
)
from mycad.core.drawing_groups import DrawingObjectRef
from mycad.core.drawing_transactions import prepare_collection_copy, prepare_collection_translation
from mycad.core.geometric_tolerance import DatumIdentifier
from mycad.core.replay_proposal import ReplayAppend
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.drawing_collection_session import DrawingCollectionSession


@pytest.mark.parametrize("action", ["move", "copy", "paste"])
def test_collection_operations_preserve_datum_arrow_style(action: str) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier("8" * 32, "A", (10, 10), (0, 0), arrow_style="open")
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    line = LineEntity(uuid4().hex, (50, 0), (60, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=0,
    )
    refs = (DrawingObjectRef("datum", datum.datum_id),)
    if action == "move":
        operation = prepare_collection_translation(session.snapshot, refs, draft.frame, (5, 3))
    elif action == "copy":
        operation = prepare_collection_copy(session.snapshot, refs, draft.frame, (5, 3))
    else:
        payload = capture_collection_clipboard(session.snapshot, refs)
        operation = prepare_collection_paste(payload, session.snapshot, (5, 3))
    session.stage(operation)
    assert session.snapshot.datums[-1].arrow_style == "open"
    assert session.snapshot.datums[-1].position_mm == (15, 13)
    session.commit()
    assert services.kernel.drawing_datum_identifiers[-1].arrow_style == "open"
