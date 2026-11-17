# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Versioned proofs for preserving tangency when an arc is split."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    rebind_retained_local_tangencies,
)
from mycad.core.exceptions import ValidationError
from mycad.core.sketch import ArcEntity, CircleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_edit import break_entity_at_point


@pytest.mark.parametrize("local", (False, True))
def test_split_arc_tangency_requires_version_46(local: bool) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 180)
    circle = CircleEntity(uuid4().hex, (0, 7), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(arc.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    first = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (arc, circle) if local else (arc,),
        constraints=(constraint,) if local else (),
    )
    app.commit_new_sketch(services, loaded, first, session_identity=0)
    params: dict[str, object] = {}
    relation: CrossSketchTangency | None = None
    if not local:
        second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, second, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(first.sketch_id, arc.entity_id),
            CrossSketchRef(second.sketch_id, circle.entity_id),
            "external",
        )
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    fragments = break_entity_at_point(arc, (5, 5))
    revised = replace(first, entities=(*fragments, circle) if local else fragments)
    if local:
        revised = replace(
            revised,
            constraints=rebind_retained_local_tangencies(
                first,
                revised,
                allow_fragment_rebind=True,
                allow_split_lines=True,
                allow_split_arcs=True,
            ),
        )
    else:
        assert relation is not None
        rebound = replace(relation, first=replace(relation.first, entity_id=fragments[1].entity_id))
        params["remove_tangencies"] = [relation.relation_id]
        params["cross_tangencies"] = [rebound.to_mapping()]
    state = revised.to_state_mapping()
    params["revisions"] = [
        {
            "sketch_id": first.sketch_id,
            "base_state_sha256": first.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=45)
    duplicate = replace(fragments[1], entity_id=uuid4().hex)
    altered_state = replace(revised, entities=(*revised.entities, duplicate)).to_state_mapping()
    original_revisions = params["revisions"]
    params["revisions"] = [
        {
            "sketch_id": first.sketch_id,
            "base_state_sha256": first.local_state_digest(),
            "entities": altered_state["entities"],
            "constraints": altered_state["constraints"],
        }
    ]
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=46)
    params["revisions"] = original_revisions
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=46)
    assert services.kernel.sketches[0] == revised
    loaded.bus.undo()
    assert services.kernel.sketches[0] == first
