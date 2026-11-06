# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent part-sketch draft state and local history."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad.core.part_sketch_session import PartSketchEditSession
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def _line() -> LineEntity:
    return LineEntity(uuid4().hex, (0, 0), (10, 0))


def test_draft_history_is_local_and_new_action_discards_redo() -> None:
    original = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = PartSketchEditSession(original)
    first, second = _line(), _line()

    session.add_entity(first)
    assert session.sketch.entities == (first,)
    assert original.entities == ()
    assert session.undo()
    assert session.sketch == original
    assert session.redo()
    assert session.sketch.entities == (first,)
    assert session.undo()
    session.add_entity(second)
    assert not session.redo()
    assert session.sketch.entities == (second,)
    assert session.generation == 5


def test_delete_entity_and_its_relations_is_one_undoable_operation() -> None:
    first, second = _line(), _line()
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    original = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (relation,))
    session = PartSketchEditSession(original)

    assert session.delete_entities((first.entity_id,)) == (relation,)
    assert session.sketch.entities == (second,)
    assert session.sketch.constraints == ()
    assert session.undo()
    assert session.sketch == original


def test_invalid_draft_edits_preserve_state_and_history() -> None:
    line = _line()
    original = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = PartSketchEditSession(original)

    with pytest.raises(ValueError, match="missing"):
        session.delete_entities((uuid4().hex,))
    with pytest.raises(ValueError, match="identity|frame"):
        session.replace_sketch(replace(original, frame=WorkPlaneFrame.xz()))
    relation = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(uuid4().hex, "start"),)
    )
    with pytest.raises(ValueError, match="missing"):
        session.replace_sketch(replace(original, constraints=(relation,)))
    assert session.sketch == original
    assert session.generation == 0
    assert not session.undo()
