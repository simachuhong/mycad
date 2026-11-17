# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Associative arrays remain replayable through the command bus."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import LoadedDocument, save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame


def _upgrade(services: app.AppServices, loaded: LoadedDocument) -> None:
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=1
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )


def test_rotated_array_versioned_creation_resize_and_replay(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (0, 5), (2, 5))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),), 90
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    assert loaded.document.commands[-1].version == 14
    assert services.kernel.associative_arrays == (array,)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "sketch.create",
            {**sketch.to_state_mapping(), "associative_arrays": [array.to_mapping()]},
            confirmed_by="local",
            version=13,
        )
    loaded.bus.execute(
        "drawing.array.update",
        {"array_id": array.array_id, "row_spacing": 0, "column_spacing": 8},
        confirmed_by="local",
    )
    moved = services.kernel.sketches[0].entities[1]
    assert isinstance(moved, LineEntity) and moved.start_mm == pytest.approx((0, 8))
    loaded.bus.undo()
    assert services.kernel.associative_arrays == (array,)
    new_ref = ArrayEntityRef(sketch.sketch_id, uuid4().hex)
    resized = replace(
        array, columns=3, members=(*array.members, ArrayMember(origin, new_ref, 0, 2))
    )
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.array.resize", {"array": resized.to_mapping()}, confirmed_by="local", version=1
        )
    assert loaded.document.commands == before
    loaded.bus.execute(
        "drawing.array.resize", {"array": resized.to_mapping()}, confirmed_by="local", version=2
    )
    member = services.kernel.sketches[0].entities[-1]
    assert isinstance(member, LineEntity) and member.start_mm == pytest.approx((0, 10))
    path = tmp_path / "rotated.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.associative_arrays == (resized,)
    reopened.bus.undo()
    assert reopened_services.kernel.associative_arrays == (array,)
    reopened.bus.redo()
    assert reopened_services.kernel.associative_arrays == (resized,)


def test_array_base_point_commands_are_versioned_and_replay(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayBasePoint
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    base = ArrayBasePoint(source=origin, reference=SketchGeometryReference(origin.entity_id, "end"))
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (origin,),
        (ArrayMember(origin, copy, 0, 1),),
        base_point=base,
    )
    old_params = {**sketch.to_state_mapping(), "associative_arrays": [array.to_mapping()]}
    with pytest.raises(ValidationError):
        loaded.bus.execute("sketch.create", old_params, "local", version=14)
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    assert loaded.document.commands[-1].version == 15
    params = {
        "array_id": array.array_id,
        "row_spacing": 0,
        "column_spacing": 5,
        "base_point": ArrayBasePoint(point_mm=(4, 6)).to_mapping(),
    }
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.update", params, "local", version=2)
    assert loaded.document.commands == before
    loaded.bus.execute("drawing.array.update", params, "local", version=3)
    assert services.kernel.sketches[0].entities == (source, target)
    assert services.kernel.associative_arrays[0].base_point == ArrayBasePoint(point_mm=(4, 6))
    path = tmp_path / "array-base.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.associative_arrays[0].base_point == ArrayBasePoint(
        point_mm=(4, 6)
    )
    reopened.bus.undo()
    assert reopened_services.kernel.associative_arrays[0].base_point == base
    reopened.bus.redo()
    assert reopened_services.kernel.associative_arrays[0].base_point == ArrayBasePoint(
        point_mm=(4, 6)
    )
    current = reopened_services.kernel.associative_arrays[0]
    added = ArrayEntityRef(sketch.sketch_id, uuid4().hex)
    enlarged = replace(
        current, columns=3, members=(*current.members, ArrayMember(origin, added, 0, 2))
    )
    with pytest.raises(ValidationError):
        reopened.bus.execute(
            "drawing.array.resize", {"array": enlarged.to_mapping()}, "local", version=2
        )
    reopened.bus.execute(
        "drawing.array.resize", {"array": enlarged.to_mapping()}, "local", version=3
    )
    assert reopened_services.kernel.associative_arrays[0] == enlarged
    reopened.bus.execute(
        "drawing.array.update",
        {
            "array_id": array.array_id,
            "row_spacing": 0,
            "column_spacing": 5,
            "reset_base_point": True,
        },
        "local",
        version=3,
    )
    assert reopened_services.kernel.associative_arrays[0].base_point is None


def test_move_array_command_is_atomic_and_replays(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayBasePoint

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (origin,),
        (ArrayMember(origin, copy, 0, 1),),
        base_point=ArrayBasePoint(point_mm=(1, 1)),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.array.move", {"array_id": array.array_id, "displacement": [0, 0]}, "local"
        )
    assert loaded.document.commands == before
    loaded.bus.execute(
        "drawing.array.move", {"array_id": array.array_id, "displacement": [2, 3]}, "local"
    )
    assert services.kernel.sketches[0].entities == (
        replace(source, start_mm=(2, 3), end_mm=(4, 3)),
        replace(target, start_mm=(7, 3), end_mm=(9, 3)),
    )
    assert services.kernel.associative_arrays[0].base_point == ArrayBasePoint(point_mm=(3, 4))
    path = tmp_path / "moved-array.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == services.kernel.sketches
    assert reopened_services.kernel.associative_arrays == services.kernel.associative_arrays
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    assert reopened_services.kernel.associative_arrays == (array,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == services.kernel.sketches


def test_move_downstream_array_replays_member_offset(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    upstream = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (refs[0],), (ArrayMember(refs[0], refs[1], 0, 1),)
    )
    downstream = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (refs[1],), (ArrayMember(refs[1], refs[2], 0, 1),)
    )
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=1, associative_arrays=(upstream, downstream)
    )
    before = loaded.document.commands
    params = {"array_id": downstream.array_id, "displacement": [2, 3]}
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.move", params, "local", version=1)
    assert loaded.document.commands == before
    loaded.bus.execute("drawing.array.move", params, "local", version=2)
    current = {array.array_id: array for array in services.kernel.associative_arrays}
    assert current[upstream.array_id].members[0].offset_mm == (2, 3)
    assert services.kernel.sketches[0].entities[0] == lines[0]
    path = tmp_path / "downstream-move.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert {a.array_id: a for a in reopened_services.kernel.associative_arrays} == current
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert {a.array_id: a for a in reopened_services.kernel.associative_arrays} == current
    state = reopened_services.kernel.sketches[0]
    revised = replace(state, entities=(replace(lines[0], end_mm=(3, 1)), *state.entities[1:]))
    mapping = revised.to_state_mapping()
    reopened.bus.execute(
        "sketch.revise",
        {
            "sketch_id": state.sketch_id,
            "base_state_sha256": state.local_state_digest(),
            "entities": mapping["entities"],
            "constraints": mapping["constraints"],
        },
        "local",
    )
    updated = reopened_services.kernel.sketches[0].entities
    assert isinstance(updated[1], LineEntity) and isinstance(updated[2], LineEntity)
    assert updated[1].end_mm == pytest.approx((10, 4))
    assert updated[2].end_mm == pytest.approx((15, 4))
    assert {a.array_id: a for a in reopened_services.kernel.associative_arrays}[
        upstream.array_id
    ].members[0].offset_mm == (2, 3)


def test_array_member_offset_command_and_reset_replay(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    first = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (refs[0],), (ArrayMember(refs[0], refs[1], 0, 1),)
    )
    second = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (refs[1],), (ArrayMember(refs[1], refs[2], 0, 1),)
    )
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=1, associative_arrays=(first, second)
    )
    loaded.bus.execute(
        "drawing.array.offset",
        {
            "array_id": first.array_id,
            "members": [{"target": refs[1].to_mapping(), "offset_mm": [2, 3]}],
        },
        "local",
    )
    arrays = {a.array_id: a for a in services.kernel.associative_arrays}
    assert arrays[first.array_id].members[0].offset_mm == (2, 3)
    last = services.kernel.sketches[0].entities[2]
    assert isinstance(last, LineEntity) and last.start_mm == (12, 3)
    before = loaded.document.commands
    repeated = {"target": refs[1].to_mapping(), "offset_mm": [4, 5]}
    with pytest.raises(ValidationError, match="重复"):
        loaded.bus.execute(
            "drawing.array.offset",
            {"array_id": first.array_id, "members": [repeated, repeated]},
            "local",
        )
    assert loaded.document.commands == before
    loaded.bus.execute(
        "drawing.array.offset", {"array_id": first.array_id, "reset_all": True}, "local"
    )
    assert services.kernel.sketches == (sketch,)
    path = tmp_path / "reset-array-offset.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.undo()
    assert {a.array_id: a for a in reopened_services.kernel.associative_arrays}[
        first.array_id
    ].members[0].offset_mm == (2, 3)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (sketch,)


def test_old_array_command_versions_reject_member_offset(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (8, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (origin,),
        (ArrayMember(origin, copy, 0, 1, offset_mm=(3, 0)),),
    )
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "sketch.create",
            {**sketch.to_state_mapping(), "associative_arrays": [array.to_mapping()]},
            "local",
            version=15,
        )
    assert loaded.document.commands == before
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), "local")
    _upgrade(services, loaded)
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local", version=3)
    assert loaded.document.commands == before and not services.kernel.associative_arrays
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local", version=4)
    assert services.kernel.associative_arrays == (array,)
    loaded.bus.undo()
    assert not services.kernel.associative_arrays
    loaded.bus.redo()
    assert services.kernel.associative_arrays == (array,)
    new_ref = ArrayEntityRef(sketch.sketch_id, uuid4().hex)
    enlarged = replace(
        array, columns=3, members=(*array.members, ArrayMember(origin, new_ref, 0, 2))
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.array.resize", {"array": enlarged.to_mapping()}, "local", version=3
        )
    loaded.bus.execute("drawing.array.resize", {"array": enlarged.to_mapping()}, "local", version=4)
    path = tmp_path / "array-member-offset.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.associative_arrays == (enlarged,)
    reopened.bus.undo()
    assert reopened_services.kernel.associative_arrays == (array,)
    reopened.bus.redo()
    assert reopened_services.kernel.associative_arrays == (enlarged,)


def test_new_sketch_with_member_offset_selects_new_version() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (8, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (origin,),
        (ArrayMember(origin, copy, 0, 1, offset_mm=(3, 0)),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    assert loaded.document.commands[-1].version == 16
    assert services.kernel.associative_arrays == (array,)


@pytest.mark.parametrize(("rotated", "version"), [(False, 13), (True, 14)])
def test_mixed_timeline_with_member_offset_selects_new_revision_version(
    rotated: bool, version: int
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), "local")
    source = LineEntity(uuid4().hex, (0, 3), (2, 3))
    target = LineEntity(uuid4().hex, (8, 3), (8, 5) if rotated else (10, 3))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    final = replace(draft, entities=(source, target))
    moved = replace(saved, entities=(replace(saved_line, start_mm=(1, 0), end_mm=(3, 0)),))
    origin = ArrayEntityRef(draft.sketch_id, source.entity_id)
    copy = ArrayEntityRef(draft.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        draft.frame,
        1,
        2,
        0,
        5,
        (origin,),
        (ArrayMember(origin, copy, 0, 1, offset_mm=(3, 0), rotation_deg=90 if rotated else 0),),
    )
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((moved,), draft), ((moved,), final)),
        session_identity=1,
        arrays_by_step=((), (array,)),
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert loaded.document.commands[-1].version == version
    assert services.kernel.associative_arrays == (array,)
    loaded.bus.undo()
    assert not services.kernel.associative_arrays
    loaded.bus.redo()
    assert services.kernel.associative_arrays == (array,)


def test_mixed_timeline_with_interleaved_arrays_uses_new_revision_version() -> None:
    from mycad.core.associative_array import ArrayReplacement

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (0, -5), (2, -5))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), "local")
    lines = tuple(LineEntity(uuid4().hex, (x, y), (x + 2, y)) for y in (0, 5) for x in (0, 5, 10))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (lines[0], lines[3]))
    final = replace(draft, entities=lines)
    moved = replace(saved, entities=(replace(saved_line, start_mm=(1, -5), end_mm=(3, -5)),))
    refs = tuple(ArrayEntityRef(draft.sketch_id, line.entity_id) for line in lines)
    first = AssociativeRectArray(
        uuid4().hex,
        draft.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (
            ArrayMember(refs[0], refs[1], 0, 1, replacement=ArrayReplacement(refs[4])),
            ArrayMember(refs[0], refs[2], 0, 2),
        ),
    )
    second = AssociativeRectArray(
        uuid4().hex,
        draft.frame,
        1,
        3,
        0,
        5,
        (refs[3],),
        (
            ArrayMember(refs[3], refs[4], 0, 1),
            ArrayMember(refs[3], refs[5], 0, 2, replacement=ArrayReplacement(refs[2])),
        ),
    )
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((moved,), draft), ((moved,), final)),
        session_identity=1,
        arrays_by_step=((), (first, second)),
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert loaded.document.commands[-1].version == 19
    assert len(services.kernel.associative_arrays) == 2
    loaded.bus.undo()
    assert not services.kernel.associative_arrays
    loaded.bus.redo()
    assert len(services.kernel.associative_arrays) == 2


def test_mixed_timeline_with_internal_replacement_uses_new_revision_version() -> None:
    from mycad.core.associative_array import ArrayReplacement

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), "local")
    lines = tuple(LineEntity(uuid4().hex, (x, 3), (x + 2, 3)) for x in (0, 5, 10))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (lines[0],))
    final = replace(draft, entities=lines)
    moved = replace(saved, entities=(replace(saved_line, start_mm=(1, 0), end_mm=(3, 0)),))
    refs = tuple(ArrayEntityRef(draft.sketch_id, line.entity_id) for line in lines)
    array = AssociativeRectArray(
        uuid4().hex,
        draft.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (
            ArrayMember(refs[0], refs[1], 0, 1, replacement=ArrayReplacement(refs[2])),
            ArrayMember(refs[0], refs[2], 0, 2),
        ),
    )
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((moved,), draft), ((moved,), final)),
        session_identity=1,
        arrays_by_step=((), (array,)),
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert loaded.document.commands[-1].version == 18
    assert services.kernel.associative_arrays == (array,)
    loaded.bus.undo()
    assert not services.kernel.associative_arrays
    loaded.bus.redo()
    assert services.kernel.associative_arrays == (array,)


def test_move_array_preserves_dimensions_and_replays(tmp_path: Path) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = replace(source, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    dimensions = tuple(
        SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(entity.entity_id, "geometry"),),
            2.0,
            "mm",
            position_mm=(0, 3),
            text_position_mm=(1, 4),
        )
        for entity in (source, target)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target), dimensions)
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    before = loaded.document.commands
    loaded.bus.execute(
        "drawing.array.move", {"array_id": array.array_id, "displacement": [3, 2]}, "local"
    )
    moved = services.kernel.sketches[0]
    assert all(
        item.position_mm == (3, 5) and item.text_position_mm == (4, 6) for item in moved.constraints
    )
    assert all(item.value == 2 for item in moved.constraints)
    path = tmp_path / "moved-array-dimensions.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (moved,)
    reopened.bus.undo()
    assert reopened.document.commands == before
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (moved,)


def test_member_offset_preserves_dimension_and_replays(tmp_path: Path) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = replace(source, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(target.entity_id, "geometry"),),
        2.0,
        "mm",
        position_mm=(6, 2),
        text_position_mm=(6, 3),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target), (dimension,))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    before = loaded.document.commands
    loaded.bus.execute(
        "drawing.array.offset",
        {
            "array_id": array.array_id,
            "members": [{"target": copy.to_mapping(), "offset_mm": [2, 3]}],
        },
        "local",
    )
    moved = services.kernel.sketches[0]
    assert moved.constraints[0].position_mm == (8, 5)
    assert moved.constraints[0].text_position_mm == (8, 6)
    path = tmp_path / "offset-array-dimension.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (moved,)
    reopened.bus.undo()
    assert reopened.document.commands == before
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (moved,)


def test_member_rotation_command_replays_and_undoes(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = replace(source, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    before = loaded.document.commands
    loaded.bus.execute(
        "drawing.array.rotate",
        {
            "array_id": array.array_id,
            "members": [{"target": copy.to_mapping(), "angle_deg": 90, "center_offset_mm": [1, 0]}],
        },
        "local",
    )
    moved = services.kernel.sketches[0]
    line = moved.entities[1]
    assert isinstance(line, LineEntity)
    assert line.start_mm == pytest.approx((6, -1))
    assert line.end_mm == pytest.approx((6, 1))
    path = tmp_path / "rotated-array-member.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (moved,)
    reopened.bus.undo()
    assert reopened.document.commands == before
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (moved,)


@pytest.mark.parametrize("version", [1, 2])
def test_erased_array_member_replays_and_reset_restores(tmp_path: Path, version: int) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    loaded.bus.execute(
        "drawing.array.erase",
        {"array_id": array.array_id, "targets": [copy.to_mapping()]},
        "local",
        version=version,
    )
    assert services.kernel.sketches[0].entities == (source,)
    assert services.kernel.associative_arrays[0].members[0].erased_index == 1
    assert (services.kernel.associative_arrays[0].members[0].erased_neighbors is not None) == (
        version == 2
    )
    before = loaded.document.commands
    collision = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    with pytest.raises(ValidationError, match="身份被占用"):
        loaded.bus.execute("sketch.create", collision.to_state_mapping(), "local")
    assert loaded.document.commands == before
    path = tmp_path / "erased-array.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == (source,)
    with pytest.raises(ValidationError):
        reopened.bus.execute(
            "drawing.array.reset", {"array_id": array.array_id}, "local", version=1
        )
    reopened.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=2)
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].entities == (source,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (sketch,)


@pytest.mark.parametrize(("anchored", "version"), [(False, 18), (True, 19)])
def test_create_array_with_erased_member_selects_new_schema(anchored: bool, version: int) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, uuid4().hex)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (origin,),
        (
            ArrayMember(
                origin,
                copy,
                0,
                1,
                erased_index=1,
                erased_neighbors=(source.entity_id, None) if anchored else None,
            ),
        ),
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "sketch.create",
            {**sketch.to_state_mapping(), "associative_arrays": [array.to_mapping()]},
            "local",
            version=version - 1,
        )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    assert loaded.document.commands[-1].version == version
    assert services.kernel.associative_arrays == (array,)
    loaded.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=2)
    assert len(services.kernel.sketches[0].entities) == 2


def test_erasing_only_member_in_separate_sketch_restores_it() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    source_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    target_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    for sketch in (source_sketch, target_sketch):
        loaded.bus.execute("sketch.create", sketch.to_state_mapping(), "local")
    _upgrade(services, loaded)
    origin = ArrayEntityRef(source_sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(target_sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, source_sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    loaded.bus.execute(
        "drawing.array.erase", {"array_id": array.array_id, "targets": [copy.to_mapping()]}, "local"
    )
    assert (
        next(
            sketch
            for sketch in services.kernel.sketches
            if sketch.sketch_id == target_sketch.sketch_id
        ).entities
        == ()
    )
    loaded.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=2)
    assert (
        next(
            sketch
            for sketch in services.kernel.sketches
            if sketch.sketch_id == target_sketch.sketch_id
        )
        == target_sketch
    )


def test_anchored_erasure_restores_order_after_edit_and_reopen(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    other = LineEntity(uuid4().hex, (30, 0), (32, 0))
    inserted = LineEntity(uuid4().hex, (-10, 0), (-8, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target, other))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    loaded.bus.execute(
        "drawing.array.erase",
        {"array_id": array.array_id, "targets": [copy.to_mapping()]},
        "local",
        version=2,
    )
    state = services.kernel.sketches[0]
    revised = replace(state, entities=(inserted, source, other)).to_state_mapping()
    loaded.bus.execute(
        "sketch.revise",
        {
            "sketch_id": state.sketch_id,
            "base_state_sha256": state.local_state_digest(),
            "entities": revised["entities"],
            "constraints": revised["constraints"],
        },
        "local",
    )
    path = tmp_path / "anchored-erasure.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.associative_arrays[0].members[0].erased_neighbors == (
        source.entity_id,
        other.entity_id,
    )
    reopened.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=2)
    assert reopened_services.kernel.sketches[0].entities == (inserted, source, target, other)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].entities == (inserted, source, other)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches[0].entities == (inserted, source, target, other)


def test_mixed_array_and_ordinary_erase_is_one_replayable_command(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = (
        LineEntity(uuid4().hex, (0, 0), (2, 0)),
        LineEntity(uuid4().hex, (5, 0), (7, 0)),
        LineEntity(uuid4().hex, (0, 5), (2, 5)),
        LineEntity(uuid4().hex, (5, 5), (7, 5)),
        LineEntity(uuid4().hex, (20, 0), (22, 0)),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    first = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (refs[0],), (ArrayMember(refs[0], refs[1], 0, 1),)
    )
    second = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (refs[2],), (ArrayMember(refs[2], refs[3], 0, 1),)
    )
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=1, associative_arrays=(first, second)
    )
    params = {"targets": [ref.to_mapping() for ref in (refs[1], refs[3], refs[4])]}
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.erase", params, "local", version=2)
    loaded.bus.execute("drawing.array.erase", params, "local", version=3)
    assert len(loaded.document.commands) == len(before) + 1
    assert services.kernel.sketches[0].entities == (lines[0], lines[2])
    path = tmp_path / "mixed-array-erase.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == (lines[0], lines[2])
    reopened.bus.undo()
    assert reopened.document.commands == before and reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches[0].entities == (lines[0], lines[2])


@pytest.mark.parametrize("tangent_is_member", [False, True])
def test_mixed_erase_handles_cross_sketch_tangency_atomically(tangent_is_member: bool) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    member = LineEntity(uuid4().hex, (5, 0), (7, 0))
    ordinary = LineEntity(uuid4().hex, (5, 10), (7, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, member, ordinary))
    circle = CircleEntity(uuid4().hex, (6, 2 if tangent_is_member else 12), 2)
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for item in (sketch, other):
        loaded.bus.execute("sketch.create", item.to_state_mapping(), "local")
    _upgrade(services, loaded)
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, member.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(
            sketch.sketch_id, member.entity_id if tangent_is_member else ordinary.entity_id
        ),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add", {"relation": relation.to_mapping(), "revisions": []}, "local"
    )
    before = loaded.document.commands
    params = {
        "targets": [
            copy.to_mapping(),
            ArrayEntityRef(sketch.sketch_id, ordinary.entity_id).to_mapping(),
        ]
    }
    if tangent_is_member:
        with pytest.raises(ValidationError, match="跨草图相切"):
            loaded.bus.execute("drawing.array.erase", params, "local", version=3)
        assert loaded.document.commands == before and services.kernel.sketches == (sketch, other)
        assert services.kernel.cross_sketch_tangencies == (relation,)
        draft_line = LineEntity(uuid4().hex, (0, 20), (2, 20))
        draft = Sketch(uuid4().hex, sketch.frame, (draft_line,))
        with pytest.raises(ValidationError, match="跨草图相切"):
            candidate = app.stage_mixed_drawing_timeline(
                services,
                loaded,
                draft,
                (sketch, other),
                (
                    (
                        (replace(sketch, entities=(source, ordinary)), other),
                        replace(draft, entities=()),
                    ),
                ),
                session_identity=1,
            )
            preview = candidate.preview(current_session_identity=1)
            if preview.state != "succeeded":
                raise ValidationError(str(preview.failure))
        assert loaded.document.commands == before and services.kernel.sketches == (sketch, other)
    else:
        loaded.bus.execute("drawing.array.erase", params, "local", version=3)
        assert services.kernel.sketches == (replace(sketch, entities=(source,)), other)
        assert not services.kernel.cross_sketch_tangencies
        loaded.bus.undo()
        assert loaded.document.commands == before and services.kernel.sketches == (sketch, other)
        assert services.kernel.cross_sketch_tangencies == (relation,)


def test_interleaved_array_dependencies_require_new_version_and_replay(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(LineEntity(uuid4().hex, (x, y), (x + 2, y)) for y in (0, 5) for x in (0, 5, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    first = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    second = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[3],),
        (ArrayMember(refs[3], refs[4], 0, 1), ArrayMember(refs[3], refs[5], 0, 2)),
    )
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=1, associative_arrays=(first, second)
    )

    def params(array_id: str, target: ArrayEntityRef, source: ArrayEntityRef) -> dict[str, object]:
        return {
            "array_id": array_id,
            "members": [
                {
                    "target": target.to_mapping(),
                    "replacement": {"source": source.to_mapping(), "base_offset_mm": [0, 0]},
                }
            ],
        }

    loaded.bus.execute(
        "drawing.array.replace", params(first.array_id, refs[1], refs[4]), "local", version=2
    )
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="版本"):
        loaded.bus.execute(
            "drawing.array.replace", params(second.array_id, refs[5], refs[2]), "local", version=2
        )
    assert loaded.document.commands == before
    loaded.bus.execute(
        "drawing.array.replace", params(second.array_id, refs[5], refs[2]), "local", version=3
    )
    path = tmp_path / "interleaved-arrays.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == services.kernel.sketches
    reopened.bus.undo()
    assert reopened.document.commands == before
    reopened.bus.redo()
    assert reopened_services.kernel.associative_arrays == services.kernel.associative_arrays


def test_interleaved_array_creation_and_resize_select_new_versions() -> None:
    from mycad.core.associative_array import ArrayReplacement

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    _upgrade(services, loaded)
    lines = tuple(LineEntity(uuid4().hex, (x, y), (x + 2, y)) for y in (0, 5) for x in (0, 5, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    first = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (
            ArrayMember(refs[0], refs[1], 0, 1, replacement=ArrayReplacement(refs[4])),
            ArrayMember(refs[0], refs[2], 0, 2),
        ),
    )
    second = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[3],),
        (
            ArrayMember(refs[3], refs[4], 0, 1),
            ArrayMember(refs[3], refs[5], 0, 2, replacement=ArrayReplacement(refs[2])),
        ),
    )
    params = {
        **sketch.to_state_mapping(),
        "associative_arrays": [first.to_mapping(), second.to_mapping()],
    }
    with pytest.raises(ValidationError, match="版本"):
        loaded.bus.execute("sketch.create", params, "local", version=21)
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=1, associative_arrays=(first, second)
    )
    assert loaded.document.commands[-1].version == 22
    new_ref = ArrayEntityRef(sketch.sketch_id, uuid4().hex)
    resized = replace(
        first, columns=4, members=(*first.members, ArrayMember(refs[0], new_ref, 0, 3))
    )
    with pytest.raises(ValidationError, match="版本"):
        loaded.bus.execute(
            "drawing.array.resize", {"array": resized.to_mapping()}, "local", version=9
        )
    loaded.bus.execute("drawing.array.resize", {"array": resized.to_mapping()}, "local", version=10)
    assert resized in services.kernel.associative_arrays


def test_adding_interleaved_array_requires_new_version() -> None:
    from mycad.core.associative_array import ArrayReplacement

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(LineEntity(uuid4().hex, (x, y), (x + 2, y)) for y in (0, 5) for x in (0, 5, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), "local")
    _upgrade(services, loaded)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    first = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (
            ArrayMember(refs[0], refs[1], 0, 1, replacement=ArrayReplacement(refs[4])),
            ArrayMember(refs[0], refs[2], 0, 2),
        ),
    )
    second = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[3],),
        (
            ArrayMember(refs[3], refs[4], 0, 1),
            ArrayMember(refs[3], refs[5], 0, 2, replacement=ArrayReplacement(refs[2])),
        ),
    )
    loaded.bus.execute("drawing.array.add", {"array": first.to_mapping()}, "local", version=8)
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="版本"):
        loaded.bus.execute("drawing.array.add", {"array": second.to_mapping()}, "local", version=9)
    assert loaded.document.commands == before
    loaded.bus.execute("drawing.array.add", {"array": second.to_mapping()}, "local", version=10)
    assert len(services.kernel.associative_arrays) == 2
    loaded.bus.undo()
    assert loaded.document.commands == before
    loaded.bus.redo()
    assert len(services.kernel.associative_arrays) == 2


def test_internal_replacement_requires_new_version_and_replays(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    params = {
        "array_id": array.array_id,
        "members": [
            {
                "target": refs[1].to_mapping(),
                "replacement": {"source": refs[2].to_mapping(), "base_offset_mm": [0, 0]},
            }
        ],
    }
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.replace", params, "local", version=1)
    assert loaded.document.commands == before
    loaded.bus.execute("drawing.array.replace", params, "local", version=2)
    path = tmp_path / "internal-replacement.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.associative_arrays[0].members[0].replacement is not None
    reopened.bus.undo()
    assert reopened.document.commands == before
    reopened.bus.redo()
    assert reopened_services.kernel.associative_arrays[0].members[0].replacement is not None


def test_internal_replacement_creation_and_resize_use_new_versions() -> None:
    from mycad.core.associative_array import ArrayReplacement

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    _upgrade(services, loaded)
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (
            ArrayMember(refs[0], refs[1], 0, 1, replacement=ArrayReplacement(refs[2])),
            ArrayMember(refs[0], refs[2], 0, 2),
        ),
    )
    params = {**sketch.to_state_mapping(), "associative_arrays": [array.to_mapping()]}
    with pytest.raises(ValidationError, match="版本"):
        loaded.bus.execute("sketch.create", params, "local", version=20)
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    assert loaded.document.commands[-1].version == 21
    new_ref = ArrayEntityRef(sketch.sketch_id, uuid4().hex)
    resized = replace(
        array, columns=4, members=(*array.members, ArrayMember(refs[0], new_ref, 0, 3))
    )
    with pytest.raises(ValidationError, match="版本"):
        loaded.bus.execute(
            "drawing.array.resize", {"array": resized.to_mapping()}, "local", version=8
        )
    loaded.bus.execute("drawing.array.resize", {"array": resized.to_mapping()}, "local", version=9)
    assert services.kernel.associative_arrays == (resized,)


def test_extra_output_offset_is_versioned_and_replayable(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayExtraOutput
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y)) for x, y in ((0, 0), (5, 0), (20, 20), (3, -3))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    output = ArrayExtraOutput(refs[2], refs[3], refs[0], 0, 1, (2, 3))
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1),),
        extra_outputs=(output,),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    params = {
        "array_id": array.array_id,
        "members": [{"target": refs[3].to_mapping(), "offset_mm": [4, 2]}],
    }
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="版本"):
        loaded.bus.execute("drawing.array.offset", params, "local", version=1)
    assert loaded.document.commands == before
    circle = CircleEntity(uuid4().hex, (4, -1), 2)
    other = Sketch(uuid4().hex, sketch.frame, (circle,))
    loaded.bus.execute("sketch.create", other.to_state_mapping(), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketch.sketch_id, output.target.entity_id),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add", {"relation": relation.to_mapping(), "revisions": []}, "local"
    )
    with_tangent = loaded.document.commands
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute("drawing.array.offset", params, "local", version=2)
    assert loaded.document.commands == with_tangent
    loaded.bus.undo()
    loaded.bus.undo()
    assert loaded.document.commands == before
    loaded.bus.execute("drawing.array.offset", params, "local", version=2)
    updated = services.kernel.associative_arrays[0]
    assert updated.extra_outputs[0].offset_mm == (4, 2)
    assert services.kernel.sketches[0].entities[3] == replace(
        lines[3], start_mm=(7, -1), end_mm=(9, -1)
    )
    path = tmp_path / "extra-offset.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.associative_arrays == (updated,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.associative_arrays == (updated,)
    with pytest.raises(ValidationError, match="版本"):
        reopened.bus.execute(
            "drawing.array.offset",
            {"array_id": array.array_id, "reset_all": True},
            "local",
            version=1,
        )
    reopened.bus.execute(
        "drawing.array.offset", {"array_id": array.array_id, "reset_all": True}, "local", version=2
    )
    assert reopened_services.kernel.associative_arrays == (array,)
    reopened.bus.undo()
    assert reopened_services.kernel.associative_arrays == (updated,)
    next_ref = ArrayEntityRef(sketch.sketch_id, uuid4().hex)
    resized = replace(
        updated, columns=3, members=(*updated.members, ArrayMember(refs[0], next_ref, 0, 2))
    )
    with pytest.raises(ValidationError):
        reopened.bus.execute(
            "drawing.array.resize", {"array": resized.to_mapping()}, "local", version=13
        )
    reopened.bus.execute(
        "drawing.array.resize", {"array": resized.to_mapping()}, "local", version=14
    )
    assert reopened_services.kernel.associative_arrays == (resized,)
    reopened.bus.undo()
    updated_sketch = reopened_services.kernel.sketches[0]
    fresh = app.build_app(discoverers=())
    new_loaded = app.new_document(fresh, document_type="drawing2d")
    _upgrade(fresh, new_loaded)
    old_params = {**updated_sketch.to_state_mapping(), "associative_arrays": [updated.to_mapping()]}
    with pytest.raises(ValidationError):
        new_loaded.bus.execute("sketch.create", old_params, "local", version=24)
    app.commit_new_sketch(
        fresh, new_loaded, updated_sketch, session_identity=1, associative_arrays=(updated,)
    )
    assert new_loaded.document.commands[-1].version == 25
    assert fresh.kernel.associative_arrays == (updated,)


def test_extra_output_rotation_is_versioned_and_replayable(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayExtraOutput
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y)) for x, y in ((0, 0), (5, 0), (20, 20), (8, 4))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    output = ArrayExtraOutput(refs[2], refs[3], refs[0], 0, 1, offset_mm=(3, 4))
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1),),
        extra_outputs=(output,),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    params = {
        "array_id": array.array_id,
        "members": [{"target": refs[3].to_mapping(), "angle_deg": 90, "center_offset_mm": [0, 0]}],
    }
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="版本"):
        loaded.bus.execute("drawing.array.rotate", params, "local", version=1)
    assert loaded.document.commands == before
    circle = CircleEntity(uuid4().hex, (9, 6), 2)
    other = Sketch(uuid4().hex, sketch.frame, (circle,))
    loaded.bus.execute("sketch.create", other.to_state_mapping(), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketch.sketch_id, output.target.entity_id),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add", {"relation": relation.to_mapping(), "revisions": []}, "local"
    )
    with_tangent = loaded.document.commands
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute("drawing.array.rotate", params, "local", version=2)
    assert loaded.document.commands == with_tangent
    loaded.bus.undo()
    loaded.bus.undo()
    assert loaded.document.commands == before
    loaded.bus.execute("drawing.array.rotate", params, "local", version=2)
    updated = services.kernel.associative_arrays[0]
    assert updated.extra_outputs[0].rotation_deg == 90
    rotated = services.kernel.sketches[0].entities[3]
    assert isinstance(rotated, LineEntity) and rotated.start_mm == pytest.approx((8, 4))
    assert rotated.end_mm == pytest.approx((8, 6))
    next_ref = ArrayEntityRef(sketch.sketch_id, uuid4().hex)
    resized = replace(
        updated, columns=3, members=(*updated.members, ArrayMember(refs[0], next_ref, 0, 2))
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.array.resize", {"array": resized.to_mapping()}, "local", version=14
        )
    loaded.bus.execute("drawing.array.resize", {"array": resized.to_mapping()}, "local", version=15)
    assert services.kernel.associative_arrays == (resized,)
    loaded.bus.undo()
    assert services.kernel.associative_arrays == (updated,)
    path = tmp_path / "extra-rotation.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.associative_arrays == (updated,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.associative_arrays == (updated,)
    reopened.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=4)
    assert not reopened_services.kernel.associative_arrays[0].extra_outputs
    assert output.target.entity_id not in {
        entity.entity_id for entity in reopened_services.kernel.sketches[0].entities
    }
    reopened.bus.undo()
    assert reopened_services.kernel.associative_arrays == (updated,)
    rotated_sketch = reopened_services.kernel.sketches[0]
    fresh = app.build_app(discoverers=())
    new_loaded = app.new_document(fresh, document_type="drawing2d")
    _upgrade(fresh, new_loaded)
    old_params = {**rotated_sketch.to_state_mapping(), "associative_arrays": [updated.to_mapping()]}
    with pytest.raises(ValidationError):
        new_loaded.bus.execute("sketch.create", old_params, "local", version=25)
    app.commit_new_sketch(
        fresh, new_loaded, rotated_sketch, session_identity=1, associative_arrays=(updated,)
    )
    assert new_loaded.document.commands[-1].version == 26


def test_batch_rotation_of_member_and_extra_replays_atomically(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayExtraOutput

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y)) for x, y in ((0, 0), (5, 0), (20, 20), (5, 0))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    output = ArrayExtraOutput(refs[2], refs[3], refs[0], 0, 1)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1),),
        extra_outputs=(output,),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    params = {
        "array_id": array.array_id,
        "members": [
            {"target": ref.to_mapping(), "angle_deg": 90, "center_offset_mm": [0, 0]}
            for ref in (refs[1], refs[3])
        ],
    }
    before = len(loaded.document.commands)
    loaded.bus.execute("drawing.array.rotate", params, "local", version=2)
    assert len(loaded.document.commands) == before + 1
    changed = services.kernel.sketches
    for item in (changed[0].entities[1], changed[0].entities[3]):
        assert isinstance(item, LineEntity)
        assert item.start_mm == pytest.approx((5, 0)) and item.end_mm == pytest.approx((5, 2))
    path = tmp_path / "batch-rotation.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == changed
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == changed


@pytest.mark.parametrize("rotated", [False, True])
def test_extra_output_offset_replace_requires_new_command_version(rotated: bool) -> None:
    from mycad.core.associative_array import ArrayExtraOutput

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y)) for x, y in ((0, 0), (5, 0), (20, 20), (20, 25))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (refs[0],), (ArrayMember(refs[0], refs[1], 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    output = ArrayExtraOutput(
        refs[3],
        ArrayEntityRef(sketch.sketch_id, uuid4().hex),
        refs[0],
        0,
        1,
        (0, -5),
        (3, 4),
        90 if rotated else 0,
    )
    params = {
        "array_id": array.array_id,
        "members": [
            {
                "target": refs[1].to_mapping(),
                "replacement": {
                    "source": refs[2].to_mapping(),
                    "base_offset_mm": [0, 0],
                    "anchor_source": refs[0].to_mapping(),
                },
            }
        ],
        "extra_outputs": [output.to_mapping()],
    }
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.replace", params, "local", version=7 if rotated else 6)
    assert loaded.document.commands == before
    loaded.bus.execute("drawing.array.replace", params, "local", version=8 if rotated else 7)
    assert services.kernel.associative_arrays[0].extra_outputs == (output,)
    extra = next(
        item
        for item in services.kernel.sketches[0].entities
        if item.entity_id == output.target.entity_id
    )
    assert isinstance(extra, LineEntity)
    assert extra.start_mm == pytest.approx((3, 4) if rotated else (8, 9))
    assert extra.end_mm == pytest.approx((3, 6) if rotated else (10, 9))
    loaded.bus.undo()
    assert services.kernel.associative_arrays == (array,)


@pytest.mark.parametrize("rotated", [False, True])
def test_add_array_with_extra_position_requires_new_command_version(rotated: bool) -> None:
    from mycad.core.associative_array import ArrayExtraOutput

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y)) for x, y in ((0, 0), (5, 0), (20, 20), (8, 4))
    )
    if rotated:
        lines = (*lines[:3], replace(lines[3], end_mm=(8, 6)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), "local")
    _upgrade(services, loaded)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    output = ArrayExtraOutput(
        refs[2], refs[3], refs[0], 0, 1, offset_mm=(3, 4), rotation_deg=90 if rotated else 0
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1),),
        extra_outputs=(output,),
    )
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.array.add",
            {"array": array.to_mapping()},
            "local",
            version=13 if rotated else 12,
        )
    assert loaded.document.commands == before
    loaded.bus.execute(
        "drawing.array.add", {"array": array.to_mapping()}, "local", version=14 if rotated else 13
    )
    assert services.kernel.associative_arrays == (array,)
    loaded.bus.undo()
    assert not services.kernel.associative_arrays


def test_resize_with_removed_extra_output_is_versioned_and_replayable(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayExtraOutput
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y))
        for x, y in ((0, 0), (5, 0), (10, 0), (20, 20), (10, 0))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in lines)
    output = ArrayExtraOutput(refs[3], refs[4], refs[0], 0, 2)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
        extra_outputs=(output,),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    smaller = replace(array, columns=2, members=(array.members[0],), extra_outputs=())
    circle = CircleEntity(uuid4().hex, (11, 2), 2)
    other = Sketch(uuid4().hex, sketch.frame, (circle,))
    loaded.bus.execute("sketch.create", other.to_state_mapping(), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketch.sketch_id, output.target.entity_id),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add", {"relation": relation.to_mapping(), "revisions": []}, "local"
    )
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute(
            "drawing.array.resize", {"array": smaller.to_mapping()}, "local", version=13
        )
    assert loaded.document.commands == before and services.kernel.cross_sketch_tangencies == (
        relation,
    )
    loaded.bus.undo()
    loaded.bus.undo()
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.array.resize", {"array": smaller.to_mapping()}, "local", version=12
        )
    loaded.bus.execute("drawing.array.resize", {"array": smaller.to_mapping()}, "local", version=13)
    assert services.kernel.sketches[0].entities == (lines[0], lines[1], lines[3])
    path = tmp_path / "resize-extra.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    assert reopened_services.kernel.associative_arrays == (array,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches[0].entities == (lines[0], lines[1], lines[3])


def test_cell_replace_with_extra_output_is_versioned_and_replayable(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayExtraOutput
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y))
        for x, y in ((0, 0), (0, 4), (5, 0), (5, 4), (20, 20), (20, 25), (20, 30))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        refs[:2],
        (ArrayMember(refs[0], refs[2], 0, 1), ArrayMember(refs[1], refs[3], 0, 1)),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    output = ArrayExtraOutput(
        refs[6], ArrayEntityRef(sketch.sketch_id, uuid4().hex), refs[0], 0, 1, (0, -10)
    )
    params = {
        "array_id": array.array_id,
        "members": [
            {
                "target": refs[2].to_mapping(),
                "replacement": {
                    "source": refs[4].to_mapping(),
                    "base_offset_mm": [0, 0],
                    "anchor_source": refs[0].to_mapping(),
                },
            },
            {
                "target": refs[3].to_mapping(),
                "replacement": {
                    "source": refs[5].to_mapping(),
                    "base_offset_mm": [0, -5],
                    "anchor_source": refs[0].to_mapping(),
                },
            },
        ],
        "extra_outputs": [output.to_mapping()],
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.replace", params, "local", version=5)
    loaded.bus.execute("drawing.array.replace", params, "local", version=6)
    changed = services.kernel.sketches
    assert output.target.entity_id in {item.entity_id for item in changed[0].entities}
    downstream_line = LineEntity(uuid4().hex, (10, 10), (12, 10))
    downstream_sketch = Sketch(uuid4().hex, sketch.frame, (downstream_line,))
    loaded.bus.execute("sketch.create", downstream_sketch.to_state_mapping(), "local")
    downstream = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (output.target,),
        (
            ArrayMember(
                output.target,
                ArrayEntityRef(downstream_sketch.sketch_id, downstream_line.entity_id),
                0,
                1,
            ),
        ),
    )
    loaded.bus.execute("drawing.array.add", {"array": downstream.to_mapping()}, "local")
    move_params = {"array_id": downstream.array_id, "displacement": [2, 0]}
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.move", move_params, "local", version=2)
    loaded.bus.execute("drawing.array.move", move_params, "local", version=3)
    upstream = next(
        item for item in services.kernel.associative_arrays if item.array_id == array.array_id
    )
    assert upstream.extra_outputs[0].base_offset_mm == pytest.approx((-2, -10))
    loaded.bus.undo()
    loaded.bus.undo()
    loaded.bus.undo()
    assert services.kernel.sketches == changed
    draft_line = LineEntity(uuid4().hex, (0, 50), (2, 50))
    draft = Sketch(uuid4().hex, sketch.frame, (draft_line,))
    erased_saved = replace(
        changed[0],
        entities=tuple(
            item for item in changed[0].entities if item.entity_id != output.target.entity_id
        ),
    )
    erased_data = erased_saved.to_state_mapping()
    old_params = {
        "revisions": [
            {
                "sketch_id": changed[0].sketch_id,
                "base_state_sha256": changed[0].local_state_digest(),
                "entities": erased_data["entities"],
                "constraints": erased_data["constraints"],
            }
        ],
        "erase_array_members": [output.target.to_mapping()],
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", old_params, "local", version=22)
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        changed,
        (((erased_saved,), replace(draft, entities=())),),
        session_identity=1,
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert loaded.document.commands[-1].version == 23
    loaded.bus.undo()
    assert services.kernel.sketches == (*changed, draft)
    loaded.bus.undo()
    assert services.kernel.sketches == changed
    circle = CircleEntity(uuid4().hex, (6, 12), 2)
    circle_sketch = Sketch(uuid4().hex, sketch.frame, (circle,))
    loaded.bus.execute("sketch.create", circle_sketch.to_state_mapping(), "local")
    tangent = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketch.sketch_id, output.target.entity_id),
        CrossSketchRef(circle_sketch.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add", {"relation": tangent.to_mapping(), "revisions": []}, "local"
    )
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=4)
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute(
            "drawing.array.erase", {"targets": [output.target.to_mapping()]}, "local", version=4
        )
    assert loaded.document.commands == before and services.kernel.cross_sketch_tangencies == (
        tangent,
    )
    loaded.bus.undo()
    loaded.bus.undo()
    assert services.kernel.sketches == changed
    path = tmp_path / "cell-extra.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == changed
    with pytest.raises(ValidationError):
        reopened.bus.execute(
            "drawing.array.reset", {"array_id": array.array_id}, "local", version=3
        )
    reopened.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=4)
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == changed
    with pytest.raises(ValidationError):
        reopened.bus.execute(
            "drawing.array.erase", {"targets": [output.target.to_mapping()]}, "local", version=3
        )
    reopened.bus.execute(
        "drawing.array.erase", {"targets": [output.target.to_mapping()]}, "local", version=4
    )
    assert output.target.entity_id not in {
        item.entity_id for item in reopened_services.kernel.sketches[0].entities
    }
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == changed
    replaced = reopened_services.kernel.associative_arrays[0]
    expanded = replace(
        replaced,
        columns=3,
        members=(
            *replaced.members,
            *(
                ArrayMember(source, ArrayEntityRef(sketch.sketch_id, uuid4().hex), 0, 2)
                for source in refs[:2]
            ),
        ),
    )
    with pytest.raises(ValidationError):
        reopened.bus.execute(
            "drawing.array.resize", {"array": expanded.to_mapping()}, "local", version=11
        )
    reopened.bus.execute(
        "drawing.array.resize", {"array": expanded.to_mapping()}, "local", version=12
    )
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == changed
    fresh_services = app.build_app(discoverers=())
    fresh = app.new_document(fresh_services, document_type="drawing2d")
    with pytest.raises(ValidationError):
        fresh.bus.execute(
            "sketch.create",
            {**changed[0].to_state_mapping(), "associative_arrays": [replaced.to_mapping()]},
            "local",
            version=23,
        )
    app.commit_new_sketch(
        fresh_services, fresh, changed[0], session_identity=1, associative_arrays=(replaced,)
    )
    assert fresh.document.commands[-1].version == 24
    later_services = app.build_app(discoverers=())
    later = app.new_document(later_services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (0, 50), (2, 50))
    saved_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    later.bus.execute("sketch.create", saved_sketch.to_state_mapping(), "local")
    excluded = {refs[2].entity_id, refs[3].entity_id, output.target.entity_id}
    draft = replace(
        changed[0],
        entities=tuple(item for item in changed[0].entities if item.entity_id not in excluded),
    )
    candidate = app.stage_mixed_drawing_timeline(
        later_services,
        later,
        draft,
        (saved_sketch,),
        (((saved_sketch,), changed[0]),),
        session_identity=1,
        arrays_by_step=((replaced,),),
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert later.document.commands[-1].version == 22
    add_services = app.build_app(discoverers=())
    added = app.new_document(add_services, document_type="drawing2d")
    added.bus.execute("sketch.create", changed[0].to_state_mapping(), "local")
    _upgrade(add_services, added)
    with pytest.raises(ValidationError):
        added.bus.execute(
            "drawing.array.add", {"array": replaced.to_mapping()}, "local", version=11
        )
    added.bus.execute("drawing.array.add", {"array": replaced.to_mapping()}, "local", version=12)
    assert add_services.kernel.associative_arrays == (replaced,)


def test_cell_replace_with_fewer_entities_is_atomic_and_replayable(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y))
        for x, y in ((0, 0), (0, 4), (5, 0), (5, 4), (20, 20))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        refs[:2],
        (ArrayMember(refs[0], refs[2], 0, 1), ArrayMember(refs[1], refs[3], 0, 1)),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    params = {
        "array_id": array.array_id,
        "members": [
            {
                "target": refs[2].to_mapping(),
                "replacement": {
                    "source": refs[4].to_mapping(),
                    "base_offset_mm": [0, 0],
                    "anchor_source": refs[0].to_mapping(),
                },
            }
        ],
        "erase_members": [refs[3].to_mapping()],
    }
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.replace", params, "local", version=4)
    loaded.bus.execute("drawing.array.replace", params, "local", version=5)
    assert len(loaded.document.commands) == len(before) + 1
    changed = services.kernel.sketches
    assert refs[3].entity_id not in {entity.entity_id for entity in changed[0].entities}
    path = tmp_path / "cell-replace-fewer.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == changed
    reopened.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=3)
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == changed
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)


def test_shared_anchor_replacement_is_versioned_and_replayable(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y))
        for x, y in ((0, 0), (0, 4), (5, 0), (5, 4), (20, 20), (20, 25))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        refs[:2],
        (ArrayMember(refs[0], refs[2], 0, 1), ArrayMember(refs[1], refs[3], 0, 1)),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    params = {
        "array_id": array.array_id,
        "members": [
            {
                "target": refs[2].to_mapping(),
                "replacement": {
                    "source": refs[4].to_mapping(),
                    "base_offset_mm": [0, 0],
                    "anchor_source": refs[0].to_mapping(),
                },
            },
            {
                "target": refs[3].to_mapping(),
                "replacement": {
                    "source": refs[5].to_mapping(),
                    "base_offset_mm": [0, -5],
                    "anchor_source": refs[0].to_mapping(),
                },
            },
        ],
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.replace", params, "local", version=3)
    loaded.bus.execute("drawing.array.replace", params, "local", version=4)
    changed = services.kernel.sketches
    replaced_array = services.kernel.associative_arrays[0]
    expanded = replace(
        replaced_array,
        columns=3,
        members=(
            *replaced_array.members,
            *(
                ArrayMember(source, ArrayEntityRef(sketch.sketch_id, uuid4().hex), 0, 2)
                for source in refs[:2]
            ),
        ),
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.array.resize", {"array": expanded.to_mapping()}, "local", version=10
        )
    loaded.bus.execute(
        "drawing.array.resize", {"array": expanded.to_mapping()}, "local", version=11
    )
    loaded.bus.undo()
    assert services.kernel.sketches == changed
    state = changed[0]
    secondary = replace(lines[1], start_mm=(0, 10), end_mm=(2, 10))
    revised = replace(
        state,
        entities=tuple(
            secondary if entity.entity_id == secondary.entity_id else entity
            for entity in state.entities
        ),
    )
    data = revised.to_state_mapping()
    loaded.bus.execute(
        "sketch.revise",
        {
            "sketch_id": state.sketch_id,
            "base_state_sha256": state.local_state_digest(),
            "entities": data["entities"],
            "constraints": data["constraints"],
        },
        "local",
    )
    assert services.kernel.sketches[0].entities[2:4] == state.entities[2:4]
    loaded.bus.undo()
    assert services.kernel.sketches == changed
    path = tmp_path / "shared-anchor.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == changed
    assert reopened_services.kernel.associative_arrays[0].members[1].replacement is not None
    assert (
        reopened_services.kernel.associative_arrays[0].members[1].replacement.anchor_source
        == refs[0]
    )
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == changed
    replacement_state = reopened_services.kernel.associative_arrays[0]
    fresh_services = app.build_app(discoverers=())
    fresh = app.new_document(fresh_services, document_type="drawing2d")
    with pytest.raises(ValidationError):
        fresh.bus.execute(
            "sketch.create",
            {
                **changed[0].to_state_mapping(),
                "associative_arrays": [replacement_state.to_mapping()],
            },
            "local",
            version=22,
        )
    app.commit_new_sketch(
        fresh_services,
        fresh,
        changed[0],
        session_identity=1,
        associative_arrays=(replacement_state,),
    )
    assert fresh.document.commands[-1].version == 23
    later_services = app.build_app(discoverers=())
    later = app.new_document(later_services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (0, 50), (2, 50))
    saved_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    later.bus.execute("sketch.create", saved_sketch.to_state_mapping(), "local")
    draft = replace(
        changed[0],
        entities=tuple(
            entity
            for entity in changed[0].entities
            if entity.entity_id not in {refs[2].entity_id, refs[3].entity_id}
        ),
    )
    candidate = app.stage_mixed_drawing_timeline(
        later_services,
        later,
        draft,
        (saved_sketch,),
        (((saved_sketch,), changed[0]),),
        session_identity=1,
        arrays_by_step=((replacement_state,),),
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert later.document.commands[-1].version == 21
    add_services = app.build_app(discoverers=())
    added = app.new_document(add_services, document_type="drawing2d")
    added.bus.execute("sketch.create", changed[0].to_state_mapping(), "local")
    _upgrade(add_services, added)
    with pytest.raises(ValidationError):
        added.bus.execute(
            "drawing.array.add", {"array": replacement_state.to_mapping()}, "local", version=10
        )
    added.bus.execute(
        "drawing.array.add", {"array": replacement_state.to_mapping()}, "local", version=11
    )
    assert add_services.kernel.associative_arrays == (replacement_state,)


def test_replaced_array_member_replays_and_resets(tmp_path: Path) -> None:
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    replacement = CircleEntity(uuid4().hex, (20, 4), 2)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target, replacement))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    other = ArrayEntityRef(sketch.sketch_id, replacement.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    loaded.bus.execute(
        "drawing.array.replace",
        {
            "array_id": array.array_id,
            "members": [
                {
                    "target": copy.to_mapping(),
                    "replacement": {"source": other.to_mapping(), "base_offset_mm": [0, 0]},
                }
            ],
        },
        "local",
    )
    changed = services.kernel.sketches[0]
    assert isinstance(changed.entities[1], CircleEntity)
    path = tmp_path / "array-replaced.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (changed,)
    with pytest.raises(ValidationError):
        reopened.bus.execute(
            "drawing.array.reset", {"array_id": array.array_id}, "local", version=2
        )
    reopened.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=3)
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (changed,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (sketch,)


def test_create_and_resize_with_replaced_member_use_new_schema() -> None:
    from mycad.core.associative_array import ArrayReplacement
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = CircleEntity(uuid4().hex, (5, 0), 2)
    replacement = CircleEntity(uuid4().hex, (20, 4), 2)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target, replacement))
    origin, copy, other = tuple(
        ArrayEntityRef(sketch.sketch_id, e.entity_id) for e in sketch.entities
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (origin,),
        (ArrayMember(origin, copy, 0, 1, replacement=ArrayReplacement(other)),),
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "sketch.create",
            {**sketch.to_state_mapping(), "associative_arrays": [array.to_mapping()]},
            "local",
            version=19,
        )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    assert loaded.document.commands[-1].version == 20
    new_ref = ArrayEntityRef(sketch.sketch_id, uuid4().hex)
    enlarged = replace(
        array, columns=3, members=(*array.members, ArrayMember(origin, new_ref, 0, 2))
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.array.resize", {"array": enlarged.to_mapping()}, "local", version=7
        )
    loaded.bus.execute("drawing.array.resize", {"array": enlarged.to_mapping()}, "local", version=8)
    assert services.kernel.associative_arrays == (enlarged,)


def test_editing_replacement_source_regenerates_member_after_reopen(tmp_path: Path) -> None:
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    replacement = CircleEntity(uuid4().hex, (20, 4), 2)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target, replacement))
    origin, copy, other = tuple(
        ArrayEntityRef(sketch.sketch_id, e.entity_id) for e in sketch.entities
    )
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    loaded.bus.execute(
        "drawing.array.replace",
        {
            "array_id": array.array_id,
            "members": [
                {
                    "target": copy.to_mapping(),
                    "replacement": {"source": other.to_mapping(), "base_offset_mm": [0, 0]},
                }
            ],
        },
        "local",
    )
    path = tmp_path / "array-live-replacement.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    state = reopened_services.kernel.sketches[0]
    without_replacement = replace(state, entities=state.entities[:2]).to_state_mapping()
    before = reopened.document.commands
    with pytest.raises(ValidationError):
        reopened.bus.execute(
            "sketch.revise",
            {
                "sketch_id": state.sketch_id,
                "base_state_sha256": state.local_state_digest(),
                "entities": without_replacement["entities"],
                "constraints": without_replacement["constraints"],
            },
            "local",
        )
    assert reopened.document.commands == before
    changed = replace(state, entities=(*state.entities[:2], replace(replacement, radius_mm=3)))
    mapping = changed.to_state_mapping()
    reopened.bus.execute(
        "sketch.revise",
        {
            "sketch_id": state.sketch_id,
            "base_state_sha256": state.local_state_digest(),
            "entities": mapping["entities"],
            "constraints": mapping["constraints"],
        },
        "local",
    )
    member = reopened_services.kernel.sketches[0].entities[1]
    assert isinstance(member, CircleEntity) and member.radius_mm == 3
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (state,)
    reopened.bus.redo()
    member = reopened_services.kernel.sketches[0].entities[1]
    assert isinstance(member, CircleEntity) and member.radius_mm == 3


def test_member_rotation_uses_new_schemas_for_creation_and_resize() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (5, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (origin,),
        (ArrayMember(origin, copy, 0, 1, rotation_deg=90),),
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "sketch.create",
            {**sketch.to_state_mapping(), "associative_arrays": [array.to_mapping()]},
            "local",
            version=16,
        )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    assert loaded.document.commands[-1].version == 17
    new_ref = ArrayEntityRef(sketch.sketch_id, uuid4().hex)
    enlarged = replace(
        array, columns=3, members=(*array.members, ArrayMember(origin, new_ref, 0, 2))
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.array.resize", {"array": enlarged.to_mapping()}, "local", version=4
        )
    loaded.bus.execute("drawing.array.resize", {"array": enlarged.to_mapping()}, "local", version=5)
    assert services.kernel.associative_arrays == (enlarged,)


def test_reset_array_restores_member_position_and_rotation_atomically(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    loaded.bus.execute(
        "drawing.array.offset",
        {
            "array_id": array.array_id,
            "members": [{"target": copy.to_mapping(), "offset_mm": [2, 3]}],
        },
        "local",
    )
    loaded.bus.execute(
        "drawing.array.rotate",
        {
            "array_id": array.array_id,
            "members": [{"target": copy.to_mapping(), "angle_deg": 90, "center_offset_mm": [1, 0]}],
        },
        "local",
    )
    overridden = services.kernel.sketches[0]
    before = loaded.document.commands
    loaded.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local")
    restored = services.kernel.sketches[0]
    assert restored == sketch
    assert services.kernel.associative_arrays == (array,)
    path = tmp_path / "reset-array-overrides.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.undo()
    assert reopened.document.commands == before
    assert reopened_services.kernel.sketches == (overridden,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (sketch,)


def test_rotated_array_add_rejects_old_version_and_replays() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (0, 5), (2, 5))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), confirmed_by="local")
    _upgrade(services, loaded)
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),), 90
    )
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local", version=1)
    assert loaded.document.commands == before
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local", version=2)
    assert services.kernel.associative_arrays == (array,)
    loaded.bus.undo()
    assert not services.kernel.associative_arrays
    loaded.bus.redo()
    assert services.kernel.associative_arrays == (array,)


def test_associative_array_command_replays_and_undoes(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), confirmed_by="local")
    _upgrade(services, loaded)
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, confirmed_by="local")
    assert services.kernel.associative_arrays == (array,)
    path = tmp_path / "array.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.associative_arrays == (array,)
    reopened.bus.undo()
    assert not reopened_services.kernel.associative_arrays
    assert reopened_services.kernel.sketches[0].entities == (source, target)
    reopened.bus.redo()
    assert reopened_services.kernel.associative_arrays == (array,)


def test_dxf_export_reports_array_relation_loss_and_preserves_geometry(tmp_path: Path) -> None:
    from mycad.formats import DXF_PROVIDER, DxfExchangeReport
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    path = tmp_path / "array.dxf"
    report = DXF_PROVIDER.write(services.kernel, path)
    assert isinstance(report, DxfExchangeReport)
    assert not report.complete and any("关联阵列" in warning for warning in report.warnings)
    assert read_sketch_dxf(path).sketch.entities == (source, target)
    loaded.bus.execute("drawing.array.remove", {"array_id": array.array_id}, confirmed_by="local")
    independent = DXF_PROVIDER.write(services.kernel, path)
    assert isinstance(independent, DxfExchangeReport) and independent.complete


def test_sketch_creation_can_commit_array_atomically_and_undo_once() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    params = {**sketch.to_state_mapping(), "associative_arrays": [array.to_mapping()]}
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("sketch.create", 11, params, "local"),),
            False,
            target_archive_version=6,
        ),
        current_session_identity=1,
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert len(loaded.document.commands) == 1
    assert services.kernel.sketches == (sketch,) and services.kernel.associative_arrays == (array,)
    loaded.bus.undo()
    assert not services.kernel.sketches and not services.kernel.associative_arrays
    loaded.bus.redo()
    assert services.kernel.sketches == (sketch,) and services.kernel.associative_arrays == (array,)
    edited = replace(source, end_mm=(3, 1))
    revised = replace(sketch, entities=(edited, target)).to_state_mapping()
    loaded.bus.execute(
        "sketch.revise",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "entities": revised["entities"],
            "constraints": revised["constraints"],
        },
        confirmed_by="local",
    )
    assert services.kernel.sketches[0].entities == (edited, replace(target, end_mm=(8, 1)))
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)


def test_atomic_array_rejected_for_part_document() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services)
    _upgrade(services, loaded)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    with pytest.raises(ValidationError, match="独立二维"):
        loaded.bus.execute(
            "sketch.create",
            {**sketch.to_state_mapping(), "associative_arrays": []},
            confirmed_by="local",
            version=11,
        )
    assert not loaded.document.commands


def test_app_commits_array_with_sketch_and_upgrades_archive(tmp_path: Path) -> None:
    from mycad.core.document import Document

    services = app.build_app(discoverers=())
    legacy = Document(services.registry, archive_version=3, document_type="drawing2d")
    path = tmp_path / "legacy.my2d"
    save_document(legacy, path)
    loaded = app.open_app_document(services, path)
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    assert services.kernel.associative_arrays == (array,)
    assert loaded.document.archive_version == 6
    assert len(loaded.document.commands) == 1
    loaded.bus.undo()
    assert not services.kernel.sketches


def test_atomic_array_respects_authoritative_drawing_layer() -> None:
    from mycad.core.sketch_layers import DEFAULT_DIM_LAYER, SketchLayer, SketchLayerTable

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    global_layers = SketchLayerTable().add(DEFAULT_DIM_LAYER).add(SketchLayer("L", locked=True))
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": global_layers.to_mapping(), "dimension_layer": "DIM"},
        confirmed_by="local",
    )
    local_layers = SketchLayerTable().add(SketchLayer("L"))
    source = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="L")
    target = LineEntity(uuid4().hex, (5, 0), (7, 0), layer_name="L")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target), layers=local_layers)
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="锁定"):
        app.commit_new_sketch(
            services, loaded, sketch, session_identity=1, associative_arrays=(array,)
        )
    assert loaded.document.commands == before and not services.kernel.sketches


def test_atomic_array_and_cross_sketch_tangency_commit_together() -> None:
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), confirmed_by="local")
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    copy = CircleEntity(uuid4().hex, (5, 2), 2)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle, copy))
    source_ref = ArrayEntityRef(draft.sketch_id, circle.entity_id)
    copy_ref = ArrayEntityRef(draft.sketch_id, copy.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        draft.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, copy_ref, 0, 1),),
    )
    app.commit_new_sketch(
        services,
        loaded,
        draft,
        session_identity=1,
        cross_tangent_pairs=((line.entity_id, circle.entity_id),),
        associative_arrays=(array,),
    )
    assert len(services.kernel.cross_sketch_tangencies) == 1
    assert services.kernel.associative_arrays == (array,)
    loaded.bus.undo()
    assert not services.kernel.cross_sketch_tangencies and not services.kernel.associative_arrays
    loaded.bus.redo()
    assert len(
        services.kernel.cross_sketch_tangencies
    ) == 1 and services.kernel.associative_arrays == (array,)


def test_update_array_angle_replays_and_undoes(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    params = {"array_id": array.array_id, "row_spacing": 0, "column_spacing": 5, "angle_deg": 90}
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.update", params, "local", version=1)
    assert loaded.document.commands == before
    loaded.bus.execute("drawing.array.update", params, "local", version=2)
    updated = services.kernel.sketches[0].entities[1]
    assert isinstance(updated, LineEntity) and updated.start_mm == pytest.approx((0, 5))
    assert services.kernel.associative_arrays[0].angle_deg == 90
    path = tmp_path / "array-angle.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.associative_arrays[0].angle_deg == 90
    reopened.bus.undo()
    assert reopened_services.kernel.associative_arrays[0].angle_deg == 0
    reopened.bus.redo()
    assert reopened_services.kernel.associative_arrays[0].angle_deg == 90


def test_update_array_spacing_replays_and_undoes(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.array.update",
            {"array_id": array.array_id, "row_spacing": 0, "column_spacing": 0},
            confirmed_by="local",
        )
    assert loaded.document.commands == before and services.kernel.sketches == (sketch,)
    loaded.bus.execute(
        "drawing.array.update",
        {"array_id": array.array_id, "row_spacing": 0, "column_spacing": 8},
        confirmed_by="local",
    )
    assert services.kernel.sketches[0].entities == (
        source,
        replace(target, start_mm=(8, 0), end_mm=(10, 0)),
    )
    assert services.kernel.associative_arrays == (replace(array, column_spacing=8),)
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)
    loaded.bus.redo()
    path = tmp_path / "updated.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == services.kernel.sketches
    assert reopened_services.kernel.associative_arrays == services.kernel.associative_arrays


def test_resize_array_replays_and_undoes(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    new_ref = ArrayEntityRef(sketch.sketch_id, uuid4().hex)
    larger = replace(array, columns=3, members=(*array.members, ArrayMember(origin, new_ref, 0, 2)))
    loaded.bus.execute("drawing.array.resize", {"array": larger.to_mapping()}, confirmed_by="local")
    assert services.kernel.associative_arrays == (larger,)
    assert services.kernel.sketches[0].entities[-1].entity_id == new_ref.entity_id
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,) and services.kernel.associative_arrays == (array,)
    loaded.bus.redo()
    path = tmp_path / "resized.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == services.kernel.sketches
    assert reopened_services.kernel.associative_arrays == (larger,)


def test_associative_array_add_rejects_invalid_geometry_without_writing() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (9, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), confirmed_by="local")
    _upgrade(services, loaded)
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, confirmed_by="local")
    assert loaded.document.commands == before
    assert services.kernel.sketches[0] == sketch
    assert not services.kernel.associative_arrays


def test_associative_array_command_rejects_non_drawing_document() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services)
    _upgrade(services, loaded)
    with pytest.raises(ValidationError, match="独立二维"):
        loaded.bus.execute("drawing.array.remove", {"array_id": uuid4().hex}, confirmed_by="local")


def test_remove_array_retains_geometry_and_allows_independent_edits() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), confirmed_by="local")
    _upgrade(services, loaded)
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, confirmed_by="local")
    loaded.bus.execute("drawing.array.remove", {"array_id": array.array_id}, confirmed_by="local")
    assert not services.kernel.associative_arrays
    assert services.kernel.sketches[0].entities == (source, target)
    edited = replace(target, end_mm=(8, 0))
    candidate = replace(sketch, entities=(source, edited)).to_state_mapping()
    loaded.bus.execute(
        "sketch.revise",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "entities": candidate["entities"],
            "constraints": candidate["constraints"],
        },
        confirmed_by="local",
    )
    assert services.kernel.sketches[0].entities == (source, edited)
    loaded.bus.undo()
    loaded.bus.undo()
    assert services.kernel.associative_arrays == (array,)
    assert services.kernel.sketches[0].entities == (source, target)


def test_array_source_edit_rejects_member_with_cross_sketch_tangency() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    circle = CircleEntity(uuid4().hex, (6, 2), 2)
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for item in (sketch, other):
        loaded.bus.execute("sketch.create", item.to_state_mapping(), confirmed_by="local")
    _upgrade(services, loaded)
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, confirmed_by="local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketch.sketch_id, target.entity_id),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add",
        {"relation": relation.to_mapping(), "revisions": []},
        confirmed_by="local",
    )
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute(
            "drawing.array.update",
            {"array_id": array.array_id, "row_spacing": 0, "column_spacing": 8},
            confirmed_by="local",
        )
    assert loaded.document.commands == before and services.kernel.sketches == (sketch, other)
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute(
            "drawing.array.offset",
            {
                "array_id": array.array_id,
                "members": [{"target": target_ref.to_mapping(), "offset_mm": [0, 2]}],
            },
            confirmed_by="local",
        )
    assert loaded.document.commands == before and services.kernel.sketches == (sketch, other)
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute(
            "drawing.array.rotate",
            {
                "array_id": array.array_id,
                "members": [
                    {"target": target_ref.to_mapping(), "angle_deg": 90, "center_offset_mm": [0, 0]}
                ],
            },
            confirmed_by="local",
        )
    assert loaded.document.commands == before and services.kernel.sketches == (sketch, other)
    for operation, change in (
        ("offset", {"offset_mm": [0, 2]}),
        ("rotate", {"angle_deg": 90, "center_offset_mm": [0, 0]}),
    ):
        with pytest.raises(ValidationError, match="跨草图相切"):
            loaded.bus.execute(
                "drawing.array.batch_override",
                {
                    "operation": operation,
                    "groups": [
                        {
                            "array_id": array.array_id,
                            "members": [{"target": target_ref.to_mapping(), **change}],
                        }
                    ],
                },
                confirmed_by="local",
            )
        assert loaded.document.commands == before and services.kernel.sketches == (sketch, other)
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute(
            "drawing.array.erase",
            {"array_id": array.array_id, "targets": [target_ref.to_mapping()]},
            confirmed_by="local",
        )
    assert loaded.document.commands == before and services.kernel.sketches == (sketch, other)
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute(
            "drawing.array.replace",
            {
                "array_id": array.array_id,
                "members": [
                    {
                        "target": target_ref.to_mapping(),
                        "replacement": {
                            "source": ArrayEntityRef(
                                other.sketch_id, circle.entity_id
                            ).to_mapping(),
                            "base_offset_mm": [0, 0],
                        },
                    }
                ],
            },
            confirmed_by="local",
        )
    assert loaded.document.commands == before and services.kernel.sketches == (sketch, other)
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute(
            "drawing.array.move",
            {"array_id": array.array_id, "displacement": [0, 2]},
            confirmed_by="local",
        )
    assert loaded.document.commands == before and services.kernel.sketches == (sketch, other)
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute(
            "drawing.array.update",
            {"array_id": array.array_id, "row_spacing": 0, "column_spacing": 5, "angle_deg": 90},
            confirmed_by="local",
            version=2,
        )
    assert loaded.document.commands == before and services.kernel.sketches == (sketch, other)
    moved = replace(source, start_mm=(0, 1), end_mm=(2, 1))
    candidate = replace(sketch, entities=(moved, target)).to_state_mapping()
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute(
            "sketch.revise",
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": candidate["entities"],
                "constraints": candidate["constraints"],
            },
            confirmed_by="local",
        )
    assert loaded.document.commands == before
    assert services.kernel.sketches == (sketch, other)


def test_resize_rejects_removing_member_with_cross_sketch_tangency() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    first = LineEntity(uuid4().hex, (5, 0), (7, 0))
    last = LineEntity(uuid4().hex, (10, 0), (12, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, first, last))
    circle = CircleEntity(uuid4().hex, (11, 2), 2)
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for item in (sketch, other):
        loaded.bus.execute("sketch.create", item.to_state_mapping(), confirmed_by="local")
    _upgrade(services, loaded)
    refs = tuple(
        ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in (source, first, last)
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, confirmed_by="local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketch.sketch_id, last.entity_id),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add",
        {"relation": relation.to_mapping(), "revisions": []},
        confirmed_by="local",
    )
    smaller = replace(array, columns=2, members=array.members[:1])
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="跨草图相切"):
        loaded.bus.execute(
            "drawing.array.resize", {"array": smaller.to_mapping()}, confirmed_by="local"
        )
    assert loaded.document.commands == before and services.kernel.sketches == (sketch, other)


def test_associative_array_source_revision_propagates_and_replays(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), confirmed_by="local")
    _upgrade(services, loaded)
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, confirmed_by="local")
    edited = replace(source, end_mm=(3, 1))
    candidate = replace(sketch, entities=(edited, target)).to_state_mapping()
    loaded.bus.execute(
        "sketch.revise",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "entities": candidate["entities"],
            "constraints": candidate["constraints"],
        },
        confirmed_by="local",
    )
    expected = (edited, replace(target, end_mm=(8, 1)))
    assert services.kernel.sketches[0].entities == expected
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (source, target)
    loaded.bus.redo()
    assert services.kernel.sketches[0].entities == expected
    path = tmp_path / "array-revise.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.associative_arrays == (array,)
    assert reopened_services.kernel.sketches[0].entities == expected


@pytest.mark.parametrize("change", ["target_edit", "target_delete", "source_delete"])
def test_associative_array_rejects_direct_edit_without_writing(change: str) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), confirmed_by="local")
    _upgrade(services, loaded)
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, confirmed_by="local")
    items = (
        (source, replace(target, end_mm=(9, 0)))
        if change == "target_edit"
        else (source,)
        if change == "target_delete"
        else (target,)
    )
    changed = replace(sketch, entities=items).to_state_mapping()
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "sketch.revise",
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": changed["entities"],
                "constraints": changed["constraints"],
            },
            confirmed_by="local",
        )
    assert loaded.document.commands == before
    assert services.kernel.sketches[0] == sketch
    assert services.kernel.associative_arrays == (array,)


@pytest.mark.parametrize("angle", [0, 90])
def test_revision_can_add_array_atomically_with_new_members(angle: int) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = (
        LineEntity(uuid4().hex, (5, 0), (7, 0))
        if angle == 0
        else LineEntity(uuid4().hex, (0, 5), (2, 5))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), confirmed_by="local")
    _upgrade(services, loaded)
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),), angle
    )
    revised = replace(sketch, entities=(source, target)).to_state_mapping()
    if angle:
        before = loaded.document.commands
        with pytest.raises(ValidationError):
            loaded.bus.execute(
                "drawing.sketch.revise",
                {
                    "revisions": [
                        {
                            "sketch_id": sketch.sketch_id,
                            "base_state_sha256": sketch.local_state_digest(),
                            "entities": revised["entities"],
                            "constraints": revised["constraints"],
                        }
                    ],
                    "associative_arrays": [array.to_mapping()],
                },
                confirmed_by="local",
                version=10,
            )
        assert loaded.document.commands == before
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": revised["entities"],
                    "constraints": revised["constraints"],
                }
            ],
            "associative_arrays": [array.to_mapping()],
        },
        confirmed_by="local",
        version=11 if angle else 6,
    )
    assert services.kernel.associative_arrays == (array,) and services.kernel.sketches[
        0
    ].entities == (source, target)
    loaded.bus.undo()
    assert not services.kernel.associative_arrays and services.kernel.sketches == (sketch,)
    loaded.bus.redo()
    assert services.kernel.associative_arrays == (array,)


@pytest.mark.parametrize("angle", [0, 90])
@pytest.mark.parametrize("has_base", [False, True])
def test_mixed_timeline_commits_array_with_its_geometry_step(
    tmp_path: Path, angle: int, has_base: bool
) -> None:
    from mycad.core.associative_array import ArrayBasePoint
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), confirmed_by="local")
    source = LineEntity(uuid4().hex, (0, 3), (2, 3))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    moved = replace(saved, entities=(replace(saved_line, start_mm=(1, 0), end_mm=(3, 0)),))
    target = (
        LineEntity(uuid4().hex, (5, 3), (7, 3))
        if angle == 0
        else LineEntity(uuid4().hex, (0, 8), (2, 8))
    )
    final_draft = replace(draft, entities=(source, target))
    origin, copy = (
        ArrayEntityRef(draft.sketch_id, source.entity_id),
        ArrayEntityRef(draft.sketch_id, target.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex, draft.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),), angle
    )
    if has_base:
        array = replace(
            array,
            base_point=ArrayBasePoint(
                source=origin, reference=SketchGeometryReference(origin.entity_id, "end")
            ),
        )
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((moved,), draft), ((moved,), final_draft)),
        session_identity=1,
        arrays_by_step=((), (array,)),
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert loaded.document.commands[-1].version == (12 if has_base else 11 if angle else 6)
    assert services.kernel.associative_arrays == (array,) and services.kernel.sketches == (
        moved,
        final_draft,
    )
    loaded.bus.undo()
    assert not services.kernel.associative_arrays and services.kernel.sketches == (moved, draft)
    loaded.bus.redo()
    assert services.kernel.associative_arrays == (array,) and services.kernel.sketches == (
        moved,
        final_draft,
    )
    path = tmp_path / "mixed-array.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.associative_arrays == (array,)
    assert reopened_services.kernel.sketches == (moved, final_draft)


@pytest.mark.parametrize("rotated", [False, True])
def test_mixed_timeline_adds_array_with_extra_position_override(
    tmp_path: Path, rotated: bool
) -> None:
    from mycad.core.associative_array import ArrayExtraOutput

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (0, 10), (2, 10))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), "local")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    replacement = LineEntity(uuid4().hex, (20, 20), (22, 20))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    extra = LineEntity(uuid4().hex, (8, 4), (8, 6) if rotated else (10, 4))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, replacement))
    final_draft = replace(draft, entities=(source, replacement, target, extra))
    refs = tuple(
        ArrayEntityRef(draft.sketch_id, entity.entity_id) for entity in final_draft.entities
    )
    output = ArrayExtraOutput(
        refs[1], refs[3], refs[0], 0, 1, offset_mm=(3, 4), rotation_deg=90 if rotated else 0
    )
    array = AssociativeRectArray(
        uuid4().hex,
        draft.frame,
        1,
        2,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 0, 1),),
        extra_outputs=(output,),
    )
    moved = replace(saved, entities=(replace(saved_line, start_mm=(1, 10), end_mm=(3, 10)),))
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((moved,), final_draft),),
        session_identity=1,
        arrays_by_step=((array,),),
        initial_associative_arrays=(),
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    command = loaded.document.commands[-1]
    assert command.id == "drawing.sketch.revise" and command.version == (25 if rotated else 24)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise", command.params, "local", version=24 if rotated else 23
        )
    assert services.kernel.associative_arrays == (array,)
    path = tmp_path / "mixed-extra-offset.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.associative_arrays == (array,)
    reopened.bus.undo()
    assert not reopened_services.kernel.associative_arrays
    reopened.bus.redo()
    assert reopened_services.kernel.associative_arrays == (array,)


def test_mixed_timeline_erases_saved_array_member_and_draft_as_one_step(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    member = LineEntity(uuid4().hex, (5, 0), (7, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, member))
    origin = ArrayEntityRef(saved.sketch_id, source.entity_id)
    target = ArrayEntityRef(saved.sketch_id, member.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, saved.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, target, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, saved, session_identity=1, associative_arrays=(array,))
    draft_line = LineEntity(uuid4().hex, (0, 10), (2, 10))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (draft_line,))
    erased_saved = replace(saved, entities=(source,))
    erased_draft = replace(draft, entities=())
    candidate = app.stage_mixed_drawing_timeline(
        services, loaded, draft, (saved,), (((erased_saved,), erased_draft),), session_identity=1
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert services.kernel.sketches == (erased_saved, erased_draft)
    assert services.kernel.associative_arrays[0].members[0].erased_index is not None
    loaded.bus.undo()
    assert services.kernel.sketches == (saved, draft)
    assert services.kernel.associative_arrays == (array,)
    loaded.bus.redo()
    assert services.kernel.sketches == (erased_saved, erased_draft)
    loaded.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=3)
    assert services.kernel.sketches == (saved, erased_draft)
    loaded.bus.undo()
    assert services.kernel.sketches == (erased_saved, erased_draft)
    path = tmp_path / "mixed-draft-array-erase.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (erased_saved, erased_draft)
    assert reopened_services.kernel.associative_arrays == services.kernel.associative_arrays


def test_revision_array_rejects_preexisting_target_without_writing() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), confirmed_by="local")
    _upgrade(services, loaded)
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    state = sketch.to_state_mapping()
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "associative_arrays": [array.to_mapping()],
    }
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="本次修订创建"):
        loaded.bus.execute("drawing.sketch.revise", params, confirmed_by="local", version=6)
    assert loaded.document.commands == before and services.kernel.sketches == (sketch,)
    assert not services.kernel.associative_arrays


def test_mixed_timeline_rejects_stale_array_snapshot() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), confirmed_by="local")
    source = LineEntity(uuid4().hex, (0, 3), (2, 3))
    target = LineEntity(uuid4().hex, (5, 3), (7, 3))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    with_array = replace(draft, entities=(source, target))
    stale = replace(draft, entities=(replace(source, end_mm=(3, 3)), target))
    origin, copy = (
        ArrayEntityRef(draft.sketch_id, source.entity_id),
        ArrayEntityRef(draft.sketch_id, target.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex, draft.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="关联阵列不一致"):
        app.stage_mixed_drawing_timeline(
            services,
            loaded,
            draft,
            (saved,),
            (((saved,), with_array), ((saved,), stale)),
            session_identity=1,
            arrays_by_step=((array,), (array,)),
        )
    assert loaded.document.commands == before and services.kernel.sketches == (saved,)


@pytest.mark.parametrize("angle", [0, 90])
@pytest.mark.parametrize("has_base", [False, True])
def test_mixed_timeline_retains_array_created_before_mixed_change(
    angle: int, has_base: bool
) -> None:
    from mycad.core.associative_array import ArrayBasePoint
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), confirmed_by="local")
    source = LineEntity(uuid4().hex, (0, 3), (2, 3))
    target = (
        LineEntity(uuid4().hex, (5, 3), (7, 3))
        if angle == 0
        else LineEntity(uuid4().hex, (0, 8), (2, 8))
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(draft.sketch_id, source.entity_id)
    copy = ArrayEntityRef(draft.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, draft.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),), angle
    )
    if has_base:
        array = replace(
            array,
            base_point=ArrayBasePoint(
                source=origin, reference=SketchGeometryReference(origin.entity_id, "end")
            ),
        )
    moved = replace(saved, entities=(replace(line, start_mm=(1, 0), end_mm=(3, 0)),))
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((moved,), draft),),
        session_identity=1,
        arrays_by_step=((array,),),
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert loaded.document.commands[-2].version == (15 if has_base else 14 if angle else 11)
    assert services.kernel.associative_arrays == (array,) and services.kernel.sketches == (
        moved,
        draft,
    )
    loaded.bus.undo()
    assert services.kernel.associative_arrays == (array,) and services.kernel.sketches == (
        saved,
        draft,
    )


@pytest.mark.parametrize("tamper", [False, True])
@pytest.mark.parametrize("rotated", [False, True])
def test_mixed_scaled_source_propagates_to_array_in_shifted_frame(
    tmp_path: Path, tamper: bool, rotated: bool
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), confirmed_by="local")
    frame = WorkPlaneFrame(
        origin_mm=(10, 0, 0),
        u_axis=(0, 1, 0) if rotated else (1, 0, 0),
        v_axis=(-1, 0, 0) if rotated else (0, 1, 0),
        normal=(0, 0, 1),
    )
    target = LineEntity(
        uuid4().hex, (5, 10) if rotated else (-5, 0), (5, 8) if rotated else (-3, 0)
    )
    draft = Sketch(uuid4().hex, frame, (target,))
    origin = ArrayEntityRef(saved.sketch_id, source.entity_id)
    copy = ArrayEntityRef(draft.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, copy, 0, 1),)
    )
    changed_saved = replace(saved, entities=(replace(source, end_mm=(4, 0)),))
    end = (5, 6.5 if tamper else 6) if rotated else (-0.5 if tamper else -1, 0)
    changed_draft = replace(draft, entities=(replace(target, end_mm=end),))
    before = loaded.document.commands
    if tamper or rotated:
        with pytest.raises(ValidationError, match="关联阵列"):
            app.stage_mixed_drawing_timeline(
                services,
                loaded,
                draft,
                (saved,),
                (((changed_saved,), changed_draft),),
                session_identity=1,
                arrays_by_step=((array,),),
                initial_associative_arrays=(array,),
            )
        assert loaded.document.commands == before and services.kernel.sketches == (saved,)
        return
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((changed_saved,), changed_draft),),
        session_identity=1,
        arrays_by_step=((array,),),
        initial_associative_arrays=(array,),
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert services.kernel.sketches == (changed_saved, changed_draft)
    path = tmp_path / "scaled-cross-frame.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (changed_saved, changed_draft)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (saved, draft)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (changed_saved, changed_draft)


def test_mixed_scaled_array_source_rejects_driving_constraint_atomically() -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    constraint = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(source.entity_id, "geometry"),), 2, "mm"
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,), (constraint,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), confirmed_by="local")
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    origin = ArrayEntityRef(saved.sketch_id, source.entity_id)
    member = ArrayEntityRef(draft.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, draft.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, member, 0, 1),)
    )
    changed_saved = replace(saved, entities=(replace(source, end_mm=(4, 0)),))
    changed_draft = replace(draft, entities=(replace(target, end_mm=(9, 0)),))
    before = loaded.document.commands
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((changed_saved,), changed_draft),),
        session_identity=1,
        arrays_by_step=((array,),),
        initial_associative_arrays=(array,),
    )
    assert candidate.preview(current_session_identity=1).state == "failed"
    assert loaded.document.commands == before and services.kernel.sketches == (saved,)


def test_mixed_timeline_adds_array_and_cross_tangency_in_one_step() -> None:
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), confirmed_by="local")
    moved_line = replace(line, start_mm=(-9, 0), end_mm=(11, 0))
    moved = replace(saved, entities=(moved_line,))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    copy = CircleEntity(uuid4().hex, (5, 2), 2)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    final_draft = replace(draft, entities=(circle, copy))
    origin, target = (
        ArrayEntityRef(draft.sketch_id, circle.entity_id),
        ArrayEntityRef(draft.sketch_id, copy.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex, draft.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, target, 0, 1),)
    )
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((moved,), draft), ((moved,), final_draft)),
        session_identity=1,
        arrays_by_step=((), (array,)),
        cross_pairs_by_step=((), ((line.entity_id, circle.entity_id),)),
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert (
        services.kernel.associative_arrays == (array,)
        and len(services.kernel.cross_sketch_tangencies) == 1
    )
    loaded.bus.undo()
    assert not services.kernel.associative_arrays and not services.kernel.cross_sketch_tangencies
    assert services.kernel.sketches == (moved, draft)
    loaded.bus.redo()
    assert (
        services.kernel.associative_arrays == (array,)
        and len(services.kernel.cross_sketch_tangencies) == 1
    )


def test_dxf_export_reports_cross_sketch_tangency_and_array_loss(tmp_path: Path) -> None:
    from mycad.core.sketch import CircleEntity
    from mycad.formats import DXF_PROVIDER, DxfExchangeReport
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), confirmed_by="local")
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    copy = CircleEntity(uuid4().hex, (5, 2), 2)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle, copy))
    origin = ArrayEntityRef(draft.sketch_id, circle.entity_id)
    target = ArrayEntityRef(draft.sketch_id, copy.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, draft.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, target, 0, 1),)
    )
    app.commit_new_sketch(
        services,
        loaded,
        draft,
        session_identity=1,
        cross_tangent_pairs=((line.entity_id, circle.entity_id),),
        associative_arrays=(array,),
    )
    path = tmp_path / "linked.dxf"
    report = DXF_PROVIDER.write(services.kernel, path)
    assert isinstance(report, DxfExchangeReport)
    assert any("跨草图相切" in warning for warning in report.warnings)
    assert any("关联阵列" in warning for warning in report.warnings)
    assert read_sketch_dxf(path).sketch.entities == (line, circle, copy)


@pytest.mark.parametrize("operation", ["offset", "rotate"])
def test_cross_array_batch_override_replays_atomically(tmp_path: Path, operation: str) -> None:
    from mycad.core.associative_array import ArrayExtraOutput

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y))
        for x, y in ((0, 0), (5, 0), (10, 0), (20, 20), (10, 0))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    arrays = tuple(
        AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            1,
            2,
            0,
            distance,
            (refs[0],),
            (ArrayMember(refs[0], refs[index], 0, 1),),
        )
        for index, distance in ((1, 5), (2, 10))
    )
    extra = ArrayExtraOutput(refs[3], refs[4], refs[0], 0, 1)
    arrays = (arrays[0], replace(arrays[1], extra_outputs=(extra,)))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=arrays)
    groups = [
        {
            "array_id": array.array_id,
            "members": [
                {
                    "target": refs[1 if index == 1 else 4].to_mapping(),
                    **(
                        {"offset_mm": [2, 3]}
                        if operation == "offset"
                        else {
                            "angle_deg": 90,
                            "center_offset_mm": [0, 0],
                        }
                    ),
                }
            ],
        }
        for index, array in enumerate(arrays, 1)
    ]
    params = {"operation": operation, "groups": groups}
    before = len(loaded.document.commands)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.array.batch_override",
            {"operation": operation, "groups": [groups[0], groups[0]]},
            "local",
        )
    assert len(loaded.document.commands) == before
    loaded.bus.execute("drawing.array.batch_override", params, "local")
    assert len(loaded.document.commands) == before + 1
    changed = services.kernel.sketches
    for index, entity_index in ((1, 1), (2, 4)):
        entity = changed[0].entities[entity_index]
        assert isinstance(entity, LineEntity)
        if operation == "offset":
            assert entity.start_mm == pytest.approx((index * 5 + 2, 3))
        else:
            assert entity.end_mm == pytest.approx((index * 5, 2))
    path = tmp_path / f"batch-{operation}.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == changed
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == changed


def test_member_and_dimension_erasure_versioned_replay(tmp_path: Path) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(target.entity_id, "geometry"),),
        2.0,
        "mm",
        driving=False,
        position_mm=(6, 2),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target), (dimension,))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    member = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, member, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    revised = replace(sketch, entities=(source,), constraints=())
    state = revised.to_state_mapping()
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "erase_array_members": [member.to_mapping()],
    }
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=20)
    assert loaded.document.commands == before and services.kernel.sketches == (sketch,)
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=26)
    assert services.kernel.sketches == (revised,)
    assert services.kernel.associative_arrays[0].members[0].erased_index is not None
    path = tmp_path / "member-dimension.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (revised,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (revised,)
