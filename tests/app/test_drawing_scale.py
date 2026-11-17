# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Uniform scaling uses replayable sketch revisions and constraint guards."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.replay_proposal import ReplayChangeSet
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_edit import scale_entities


@pytest.mark.parametrize("constrained", [False, True])
def test_scale_revision_replays_or_rejects_driving_constraint(
    tmp_path: Path, constrained: bool
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    dimensions = (
        (
            SketchConstraint(
                uuid4().hex,
                "length",
                (SketchGeometryReference(line.entity_id, "geometry"),),
                2,
                "mm",
            ),
        )
        if constrained
        else ()
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), dimensions)
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=1
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    changed = replace(
        sketch, entities=scale_entities(sketch.entities, (line.entity_id,), (0, 0), 2)
    )
    data = changed.to_state_mapping()
    params = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
        "entities": data["entities"],
        "constraints": data["constraints"],
    }
    before = loaded.document.commands
    if constrained:
        with pytest.raises(ValidationError, match="constraint"):
            loaded.bus.execute("sketch.revise", params, "local")
        assert loaded.document.commands == before and services.kernel.sketches == (sketch,)
        return
    loaded.bus.execute("sketch.revise", params, "local")
    assert services.kernel.sketches == (changed,)
    path = tmp_path / "scale.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (changed,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (changed,)
