# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Tangencies in a drawing cannot reference another drawing's objects."""

from uuid import uuid4

import pytest

from mycad import app
from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
from mycad.core.exceptions import ValidationError
from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame


def test_tangency_rejects_object_owned_by_another_drawing() -> None:
    root = app.build_app(discoverers=[])
    left = app.fork_app_services(root)
    right = app.fork_app_services(root)
    left_doc = app.new_document(left, document_type="drawing2d")
    right_doc = app.new_document(right, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(left, left_doc, first, session_identity=0)
    app.commit_new_sketch(right, right_doc, second, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    left_count, right_count = left_doc.document.command_count, right_doc.document.command_count
    with pytest.raises(ValidationError):
        app.commit_cross_sketch_tangency(left, left_doc, relation, session_identity=0)
    assert left.kernel.sketches == (first,) and right.kernel.sketches == (second,)
    assert not left.kernel.cross_sketch_tangencies and not right.kernel.cross_sketch_tangencies
    assert left_doc.document.command_count == left_count
    assert right_doc.document.command_count == right_count
