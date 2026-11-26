# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Conservative group translation from a candidate drawing view."""

from dataclasses import replace
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
from mycad.core.drawing_transactions import prepare_simple_collection_move
from mycad.core.exceptions import ValidationError
from mycad.core.replay_proposal import ReplayAppend
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.drawing_collection_session import DrawingCollectionSession


def test_group_delete_mixed_members_is_atomic_and_reopens(tmp_path: Path) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "文字", (1, 1))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("text", text.text_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_delete(session.snapshot, (ref,)))
    assert session.snapshot.sketches[-1].entities == ()
    assert session.snapshot.texts == () and session.snapshot.groups == ()
    session.commit()
    path = tmp_path / "delete-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (line,)
    assert services.kernel.drawing_texts == (text,)
    assert services.kernel.drawing_groups == (group,)


def test_group_delete_rejects_locked_member_before_staging() -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "文字", (1, 1), layer_name="Locked")
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("text", text.text_id)))
    snapshot = replace(
        session.snapshot,
        groups=(group,),
        texts=(text,),
        layers=session.snapshot.layers.add(SketchLayer("Locked", locked=True)),
    )
    with pytest.raises(ValidationError, match="锁定"):
        prepare_collection_delete(snapshot, (ref,))
    assert session.snapshot.sketches[-1].entities == (line,)
    assert loaded.document.commands == ()
    session.cancel()


def test_group_delete_attached_datum_and_cross_tangent_geometry_atomically(tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (0, 0),
        attachment=DatumAttachment(
            first.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    refs = (
        DrawingObjectRef("geometry", line.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
        DrawingObjectRef("datum", datum.datum_id),
    )
    group = DrawingGroup(uuid4().hex, refs)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_delete(session.snapshot, (refs[0],)))
    assert (
        session.snapshot.sketches[0].entities == () and session.snapshot.sketches[1].entities == ()
    )
    assert (
        not session.snapshot.cross_tangencies
        and not session.snapshot.datums
        and not session.snapshot.groups
    )
    session.undo()
    assert session.snapshot.sketches[:2] == (first, second)
    assert session.snapshot.cross_tangencies == (relation,) and session.snapshot.datums == (datum,)
    session.redo()
    session.commit()
    path = tmp_path / "attached-group-delete.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[:2] == (first, second)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_groups == (group,)


def test_group_delete_keeps_unrelated_attachment_and_rejects_dangling_one() -> None:
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 5), (10, 5))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 9),
        (0, 5),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(second.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in (first, second)
    )
    checkpoint = session.checkpoint()
    with pytest.raises(ValidationError, match="附着|关联|基准"):
        session.stage(prepare_collection_delete(session.snapshot, (refs[1],)))
    assert session.checkpoint() == checkpoint and session.snapshot.datums == (datum,)
    session.stage(prepare_collection_delete(session.snapshot, (refs[0],)))
    assert session.snapshot.sketches[-1].entities == (second,) and session.snapshot.datums == (
        datum,
    )
    session.undo()
    assert session.snapshot.sketches[-1].entities == (first, second)
    session.cancel()


@pytest.mark.parametrize("target_kind", ["frame", "reference_dimension"])
def test_group_delete_attached_annotation_and_target_in_dependency_order(target_kind: str) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.geometric_tolerance import (
        AnnotationAttachment,
        DatumIdentifier,
        FeatureControlFrame,
        ToleranceRow,
    )

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    if target_kind == "frame":
        frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 5))
        session.stage(
            ReplayAppend(
                "drawing.tolerance.batch", 28, {"add_frames": [frame.to_mapping()]}, "local"
            )
        )
        target_id = frame.frame_id
        target_ref = DrawingObjectRef("tolerance", target_id)
    else:
        dimension = DetachedDimension(uuid4().hex, "aligned", (0, 0), (10, 0), (0, 5), 0, 10)
        session.stage(
            ReplayAppend(
                "drawing.reference_dimensions.batch", 10, {"add": [dimension.to_mapping()]}, "local"
            )
        )
        target_id = dimension.dimension_id
        target_ref = DrawingObjectRef("reference_dimension", target_id)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (2, 5),
        annotation_attachment=AnnotationAttachment(target_kind, target_id, (2, 0)),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    before = session.checkpoint()
    with pytest.raises(ValidationError, match="附着"):
        prepare_collection_delete(session.snapshot, (target_ref,))
    assert session.checkpoint() == before
    datum_ref = DrawingObjectRef("datum", datum.datum_id)
    group = DrawingGroup(uuid4().hex, (target_ref, datum_ref))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_delete(session.snapshot, (target_ref,)))
    assert not session.snapshot.datums and not session.snapshot.frames
    assert not session.snapshot.reference_dimensions and not session.snapshot.groups
    session.undo()
    assert session.snapshot.datums == (datum,) and session.snapshot.groups == (group,)
    session.cancel()


def test_group_delete_datum_used_by_unselected_frame_is_atomic() -> None:
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.geometric_tolerance import (
        DatumIdentifier,
        DatumReference,
        FeatureControlFrame,
        ToleranceRow,
    )

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (4, 5),
    )
    session.stage(
        ReplayAppend(
            "drawing.tolerance.batch",
            28,
            {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
            "local",
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("datum", datum.datum_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.checkpoint()
    with pytest.raises(ValidationError):
        session.stage(prepare_collection_delete(session.snapshot, (ref,)))
    assert session.checkpoint() == before and session.snapshot.sketches[-1] == draft
    assert session.snapshot.groups == (group,) and session.snapshot.datums == (datum,)
    assert session.snapshot.frames == (frame,)
    session.cancel()


def test_group_delete_geometry_with_annotation_on_its_dimension() -> None:
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 2),
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (8, 5),
        (5, 2),
        annotation_attachment=AnnotationAttachment(
            "sketch_dimension", dimension.constraint_id, (0, 0), draft.sketch_id
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    with pytest.raises(ValidationError, match="附着"):
        prepare_collection_delete(session.snapshot, (ref,))
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("datum", datum.datum_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_delete(session.snapshot, (ref,)))
    assert not session.snapshot.datums and not session.snapshot.groups
    assert (
        not session.snapshot.sketches[-1].entities and not session.snapshot.sketches[-1].constraints
    )
    session.undo()
    assert session.snapshot.sketches[-1] == draft and session.snapshot.datums == (datum,)
    session.cancel()


def test_group_delete_one_tangent_member_removes_only_affected_relation() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, first.sketch_id)
    session.stage(prepare_collection_delete(session.snapshot, (ref,)))
    assert session.snapshot.sketches[0].entities == () and session.snapshot.sketches[1] == second
    assert session.snapshot.cross_tangencies == ()
    session.undo()
    assert session.snapshot.sketches[:2] == (
        first,
        second,
    ) and session.snapshot.cross_tangencies == (relation,)
    session.cancel()


def test_group_delete_geometry_and_free_annotations_is_atomic() -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (5, 5))
    datum = DatumIdentifier(uuid4().hex, "A", (8, 5), (7, 4))
    reference = DetachedDimension(uuid4().hex, "aligned", (0, 2), (2, 2), (1, 3), 0, 2)
    session.stage(
        ReplayAppend(
            "drawing.tolerance.batch",
            28,
            {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
            "local",
        )
    )
    session.stage(
        ReplayAppend(
            "drawing.reference_dimensions.batch", 10, {"add": [reference.to_mapping()]}, "local"
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            ref,
            DrawingObjectRef("tolerance", frame.frame_id),
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("reference_dimension", reference.dimension_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_delete(session.snapshot, (ref,)))
    assert session.snapshot.groups == ()
    assert session.snapshot.frames == () and session.snapshot.datums == ()
    assert session.snapshot.reference_dimensions == ()
    session.undo()
    assert session.snapshot.groups == (group,)
    assert session.snapshot.frames == (frame,) and session.snapshot.datums == (datum,)
    assert session.snapshot.reference_dimensions == (reference,)
    session.cancel()


def test_group_delete_geometry_and_dimension_removes_constraint_once() -> None:
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 2),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 8), (2, 8)),))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, saved.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (ref, DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id))
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_delete(session.snapshot, (ref,)))
    assert session.snapshot.sketches[0].entities == ()
    assert session.snapshot.sketches[0].constraints == ()
    assert session.snapshot.groups == ()
    session.undo()
    assert session.snapshot.sketches[0] == saved
    assert session.snapshot.groups == (group,)
    session.cancel()


def test_group_delete_geometry_rejects_implicitly_removed_locked_dimension() -> None:
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 2),
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    snapshot = session.snapshot
    locked_layer = replace(snapshot.layers.get(snapshot.dimension_layer), locked=True)
    locked = replace(snapshot, layers=snapshot.layers.replace(locked_layer))
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    with pytest.raises(ValidationError, match="尺寸|图层"):
        prepare_collection_delete(locked, (ref,))
    assert session.snapshot.sketches[-1] == draft and loaded.document.commands == ()
    session.cancel()


def test_group_delete_geometry_removes_its_partial_local_constraint() -> None:
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (2, 0), (2, 3))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (relation,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 9, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", first.entity_id, draft.sketch_id)
    session.stage(prepare_collection_delete(session.snapshot, (ref,)))
    assert session.snapshot.sketches[-1].entities == (second,)
    assert not session.snapshot.sketches[-1].constraints
    session.undo()
    assert session.snapshot.sketches[-1] == draft
    session.cancel()


def test_group_delete_picture_and_geometry_undoes_together(tmp_path: Path) -> None:
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    picture = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (3, 2),
        2,
        2,
    )
    session.stage(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [picture.to_mapping(version=2)]},
            "local",
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("raster", picture.image_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_delete(session.snapshot, (ref,)))
    assert session.snapshot.groups == () and session.snapshot.rasters == ()
    session.undo()
    assert session.snapshot.groups == (group,) and session.snapshot.rasters == (picture,)
    assert session.snapshot.sketches[-1].entities == (line,)
    session.redo()
    session.commit()
    path = tmp_path / "picture-group-delete.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.drawing_rasters == (picture,)


def test_group_copy_geometry_and_free_annotations_freezes_ids(tmp_path: Path) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.geometric_tolerance import (
        DatumIdentifier,
        DatumReference,
        FeatureControlFrame,
        ToleranceRow,
    )
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(uuid4().hex, "A", (8, 5), (7, 4))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (5, 5),
    )
    reference = DetachedDimension(uuid4().hex, "aligned", (0, 2), (2, 2), (1, 3), 0, 2)
    session.stage(
        ReplayAppend(
            "drawing.tolerance.batch",
            28,
            {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
            "local",
        )
    )
    session.stage(
        ReplayAppend(
            "drawing.reference_dimensions.batch", 10, {"add": [reference.to_mapping()]}, "local"
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            ref,
            DrawingObjectRef("tolerance", frame.frame_id),
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("reference_dimension", reference.dimension_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_copy(session.snapshot, (ref,), draft.frame, (0, 3)))
    copied = session.snapshot
    assert len(copied.groups) == 2 and len(copied.frames) == 2 and len(copied.datums) == 2
    assert copied.frames[1].position_mm == (5, 8)
    assert copied.datums[1].position_mm == (8, 8) and copied.datums[1].label != "A"
    assert copied.frames[1].rows[0].datums[0].datum_id == copied.datums[1].datum_id
    assert copied.frames[1].rows[0].datums[0].label == copied.datums[1].label
    assert copied.reference_dimensions[1].location_mm == (1, 6)
    session.undo()
    session.redo()
    assert session.snapshot.groups == copied.groups
    assert session.snapshot.frames == copied.frames
    assert session.snapshot.datums == copied.datums
    assert session.snapshot.reference_dimensions == copied.reference_dimensions
    session.commit()
    path = tmp_path / "annotation-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)
    reopened.bus.redo_operation()
    assert services.kernel.drawing_groups == copied.groups
    assert services.kernel.drawing_datum_identifiers == copied.datums
    assert services.kernel.drawing_tolerance_frames == copied.frames


def test_group_copy_rejects_recorded_datum_box_without_partial_changes() -> None:
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (4, 4), (0, 0), layout_mode="shared", box_size_mm=(3, 3)
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("datum", datum.datum_id)))
    snapshot = replace(session.snapshot, groups=(group,), datums=(datum,))
    with pytest.raises(ValidationError, match="文字布局"):
        prepare_collection_copy(snapshot, (ref,), draft.frame, (0, 3))
    assert session.snapshot.sketches[-1].entities == (line,)
    assert loaded.document.commands == ()
    session.cancel()


def test_group_copy_rejects_datum_relayout_that_changes_identity() -> None:
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (4, 4), (0, 0), layout_mode="shared", box_size_mm=(3, 3)
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("datum", datum.datum_id)))
    snapshot = replace(session.snapshot, groups=(group,), datums=(datum,))
    with pytest.raises(ValidationError, match="身份或关联"):
        prepare_collection_copy(
            snapshot,
            (ref,),
            draft.frame,
            (0, 3),
            datum_relayout=lambda item: replace(item, datum_id=uuid4().hex),
        )
    assert session.snapshot.sketches[-1].entities == (line,) and loaded.document.commands == ()
    session.cancel()


def test_group_mirror_copy_creates_new_group_and_undoes_after_reopen(tmp_path: Path) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.drawing_transactions import prepare_collection_mirror_copy
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 1), (2, 1))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "文字", (1, 1))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("text", text.text_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(
        prepare_collection_mirror_copy(session.snapshot, (ref,), draft.frame, (0, 0), (2, 0))
    )
    assert len(session.snapshot.groups) == 2
    original, mirrored = session.snapshot.sketches[-1].entities
    assert original == line and isinstance(mirrored, LineEntity)
    assert mirrored.start_mm == pytest.approx((1, -1))
    assert session.snapshot.texts[0] == text
    assert session.snapshot.texts[1].position_mm == pytest.approx((1, -1))
    assert set(session.snapshot.groups[1].members) == {
        DrawingObjectRef("geometry", mirrored.entity_id, draft.sketch_id),
        DrawingObjectRef("text", session.snapshot.texts[1].text_id),
    }
    session.commit()
    path = tmp_path / "mirror-copy-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (line,)
    assert services.kernel.drawing_texts == (text,)
    assert services.kernel.drawing_groups == (group,)


def test_group_mirror_of_geometry_and_text_undoes_after_reopen(tmp_path: Path) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.drawing_transactions import prepare_collection_mirror
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 1), (2, 1))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "文字", (1, 1))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("text", text.text_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_mirror(session.snapshot, (ref,), draft.frame, (0, 0), (2, 0)))
    mirrored = session.snapshot.sketches[-1].entities[0]
    assert isinstance(mirrored, LineEntity)
    assert mirrored.start_mm == pytest.approx((1, -1))
    assert session.snapshot.texts[0].position_mm == pytest.approx((1, -1))
    session.commit()
    path = tmp_path / "mirror-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (line,)
    assert services.kernel.drawing_texts == (text,)
    assert services.kernel.drawing_groups == (group,)


def test_group_rotation_of_geometry_and_text_undoes_after_reopen(tmp_path: Path) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.drawing_transactions import prepare_collection_rotation
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "文字", (1, 0))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("text", text.text_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_rotation(session.snapshot, (ref,), draft.frame, (0, 0), 90))
    rotated = session.snapshot.sketches[-1].entities[0]
    assert isinstance(rotated, LineEntity)
    assert rotated.start_mm == pytest.approx((0, 1))
    assert session.snapshot.texts[0].position_mm == pytest.approx((0, 1))
    assert session.snapshot.texts[0].rotation_deg == pytest.approx(90)
    session.commit()
    path = tmp_path / "rotate-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (line,)
    assert services.kernel.drawing_texts == (text,)
    assert services.kernel.drawing_groups == (group,)


def test_group_mirror_allows_unrelated_attached_datum_but_rejects_affected() -> None:
    from mycad.core.drawing_transactions import prepare_collection_mirror
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    selected = LineEntity(uuid4().hex, (0, 0), (2, 0))
    other = LineEntity(uuid4().hex, (0, 3), (2, 3))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (selected, other))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 3),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(other.entity_id, "start")
        ),
    )
    snapshot = replace(session.snapshot, datums=(datum,))
    ref = DrawingObjectRef("geometry", selected.entity_id, draft.sketch_id)
    prepare_collection_mirror(snapshot, (ref,), draft.frame, (0, 0), (1, 0))
    attached = replace(
        datum,
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(selected.entity_id, "start")
        ),
    )
    with pytest.raises(ValidationError, match="附着"):
        prepare_collection_mirror(
            replace(snapshot, datums=(attached,)), (ref,), draft.frame, (0, 0), (1, 0)
        )
    session.cancel()


def test_group_rotation_rejects_unsupported_member_without_changes() -> None:
    from mycad.core.drawing_transactions import prepare_collection_rotation
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(uuid4().hex, "A", (4, 4), (0, 0))
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("datum", datum.datum_id)))
    snapshot = replace(session.snapshot, groups=(group,), datums=(datum,))
    with pytest.raises(ValidationError, match="整体旋转"):
        prepare_collection_rotation(snapshot, (ref,), draft.frame, (0, 0), 90)
    assert session.snapshot.sketches[-1].entities == (line,)
    assert loaded.document.commands == ()
    session.cancel()


def test_group_mirror_includes_picture_in_same_step() -> None:
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_transactions import (
        prepare_collection_mirror,
        prepare_collection_mirror_copy,
    )

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 1), (2, 1))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    picture = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (1, 1),
        2,
        2,
    )
    session.stage(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [picture.to_mapping(version=2)]},
            "local",
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("raster", picture.image_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_mirror(session.snapshot, (ref,), draft.frame, (0, 0), (2, 0)))
    mirrored = session.snapshot.rasters[0]
    assert mirrored.origin_mm == pytest.approx((1, -1))
    assert mirrored.mirrored != picture.mirrored
    session.undo()
    assert session.snapshot.rasters == (picture,)
    assert session.snapshot.sketches[-1].entities == (line,)
    session.stage(
        prepare_collection_mirror_copy(session.snapshot, (ref,), draft.frame, (0, 0), (2, 0))
    )
    assert session.snapshot.rasters[0] == picture
    assert session.snapshot.rasters[1].origin_mm == pytest.approx((1, -1))
    assert session.snapshot.rasters[1].mirrored != picture.mirrored
    assert len(session.snapshot.groups) == 2
    session.undo()
    assert session.snapshot.rasters == (picture,)
    session.cancel()


def test_group_rotation_includes_picture_in_same_step() -> None:
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_transactions import prepare_collection_rotation

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    picture = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (1, 0),
        2,
        2,
    )
    session.stage(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [picture.to_mapping(version=2)]},
            "local",
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("raster", picture.image_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_rotation(session.snapshot, (ref,), draft.frame, (0, 0), 90))
    assert session.snapshot.rasters[0].origin_mm == pytest.approx((0, 1))
    assert session.snapshot.rasters[0].angle_deg == pytest.approx(90)
    session.undo()
    assert session.snapshot.rasters == (picture,)
    assert session.snapshot.sketches[-1].entities == (line,)
    session.cancel()


def test_group_scale_geometry_and_text_updates_size_and_undo() -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.drawing_transactions import prepare_collection_scale

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "文字", (1, 0), height_mm=2)
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("text", text.text_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_scale(session.snapshot, (ref,), draft.frame, (0, 0), 2))
    assert session.snapshot.sketches[-1].entities == (
        replace(line, start_mm=(2, 0), end_mm=(4, 0)),
    )
    assert session.snapshot.texts[0].position_mm == (2, 0)
    assert session.snapshot.texts[0].height_mm == 4
    session.undo()
    assert session.snapshot.texts == (text,) and session.snapshot.sketches[-1].entities == (line,)
    session.cancel()


def test_group_scale_picture_keeps_shared_transaction() -> None:
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_transactions import prepare_collection_scale

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    picture = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (1, 0),
        2,
        2,
    )
    session.stage(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [picture.to_mapping(version=2)]},
            "local",
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("raster", picture.image_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_scale(session.snapshot, (ref,), draft.frame, (0, 0), 2))
    assert session.snapshot.rasters[0].origin_mm == (2, 0)
    assert session.snapshot.rasters[0].width_mm == 4
    assert session.snapshot.rasters[0].height_mm == 4
    session.undo()
    assert session.snapshot.rasters == (picture,)
    assert session.snapshot.sketches[-1].entities == (line,)
    session.cancel()


def test_move_expands_only_seed_groups_and_rejects_locked_or_unsupported_members() -> None:
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    lines = tuple(LineEntity(uuid4().hex, (0, y), (2, y)) for y in (0, 5, 10))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    refs = tuple(DrawingObjectRef("geometry", line.entity_id, draft.sketch_id) for line in lines)
    groups = (DrawingGroup(uuid4().hex, refs[:2]), DrawingGroup(uuid4().hex, refs[1:]))
    snapshot = replace(session.snapshot, groups=groups)
    operation = prepare_simple_collection_move(snapshot, (refs[0],), draft.frame, (0, 3))
    session.stage(operation)
    moved = session.snapshot.sketches[-1].entities
    assert moved == (
        replace(lines[0], start_mm=(0, 3), end_mm=(2, 3)),
        replace(lines[1], start_mm=(0, 8), end_mm=(2, 8)),
        lines[2],
    )
    locked_layers = snapshot.layers.add(SketchLayer("Locked", locked=True))
    partly_locked = replace(
        draft,
        entities=(lines[0], replace(lines[1], layer_name="Locked"), lines[2]),
        layers=locked_layers,
    )
    with pytest.raises(ValidationError, match="锁定"):
        prepare_simple_collection_move(
            replace(snapshot, sketches=(partly_locked,), layers=locked_layers),
            (refs[0],),
            draft.frame,
            (0, 3),
        )
    mixed = DrawingGroup(uuid4().hex, (refs[0], DrawingObjectRef("text", uuid4().hex)))
    with pytest.raises(ValidationError, match="仅支持几何"):
        prepare_simple_collection_move(
            replace(snapshot, groups=(mixed,)), (refs[0],), draft.frame, (0, 3)
        )
    with pytest.raises(ValidationError, match="未改变"):
        prepare_simple_collection_move(snapshot, (refs[0],), draft.frame, (0, 0))
    session.cancel()


def test_copy_clones_complete_groups_and_preserves_atomic_undo(tmp_path: Path) -> None:
    from mycad.core.drawing_transactions import prepare_simple_collection_copy
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    lines = tuple(LineEntity(uuid4().hex, (0, y), (2, y)) for y in (0, 5, 10))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    refs = tuple(DrawingObjectRef("geometry", line.entity_id, draft.sketch_id) for line in lines)
    group = DrawingGroup(uuid4().hex, refs[:2], name="G")
    overlap = DrawingGroup(uuid4().hex, refs[1:])
    for item in (group, overlap):
        session.stage(ReplayAppend("drawing.group.create", 1, item.to_mapping(), "local"))
    operation = prepare_simple_collection_copy(session.snapshot, (refs[0],), draft.frame, (0, 3))
    session.stage(operation)
    assert len(session.snapshot.sketches[-1].entities) == 5
    assert len(session.snapshot.groups) == 3
    copied = session.snapshot.groups[-1]
    assert copied.name == "G 副本"
    assert {ref.object_id for ref in copied.members}.isdisjoint({line.entity_id for line in lines})
    session.commit()
    path = tmp_path / "group-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == lines
    assert services.kernel.drawing_groups == (group, overlap)
    reopened.bus.redo_operation()
    assert services.kernel.drawing_groups[-1] == copied
    assert {ref.object_id for ref in copied.members}.issubset(
        {entity.entity_id for entity in services.kernel.sketches[-1].entities}
    )


def test_move_retains_inferred_horizontal_relation() -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    relation = SketchConstraint(
        uuid4().hex,
        "horizontal",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        source="inferred",
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (relation,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    reference = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    session.stage(
        prepare_simple_collection_move(session.snapshot, (reference,), draft.frame, (0, 3))
    )
    moved = session.snapshot.sketches[-1]
    assert moved.entities == (replace(line, start_mm=(0, 3), end_mm=(2, 3)),)
    assert moved.constraints == (relation,)
    session.cancel()


def test_partial_copy_of_nonselectable_group_does_not_create_a_group() -> None:
    from mycad.core.drawing_transactions import prepare_simple_collection_copy

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    lines = tuple(LineEntity(uuid4().hex, (0, y), (2, y)) for y in (0, 5))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    refs = tuple(DrawingObjectRef("geometry", line.entity_id, draft.sketch_id) for line in lines)
    group = DrawingGroup(uuid4().hex, refs, selectable=False)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_simple_collection_copy(session.snapshot, (refs[0],), draft.frame, (0, 3)))
    assert session.snapshot.groups == (group,)
    assert len(session.snapshot.sketches[-1].entities) == 3
    session.cancel()


def test_move_keeps_geometric_relation_when_all_references_move_together() -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (2, 0), (2, 3))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (relation,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (8, 0), (10, 0)),))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    refs = tuple(
        DrawingObjectRef("geometry", line.entity_id, saved.sketch_id) for line in (first, second)
    )
    with pytest.raises(ValidationError, match="约束"):
        prepare_simple_collection_move(session.snapshot, (refs[0],), draft.frame, (0, 3))
    session.stage(prepare_simple_collection_move(session.snapshot, refs, draft.frame, (0, 3)))
    assert session.snapshot.sketches[0].constraints == (relation,)
    assert session.snapshot.sketches[0].entities == (
        replace(first, start_mm=(0, 3), end_mm=(2, 3)),
        replace(second, start_mm=(2, 3), end_mm=(2, 6)),
    )
    session.cancel()


def test_group_move_preserves_fully_selected_cross_sketch_tangency(tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_text import DrawingText
    from mycad.core.drawing_transactions import prepare_collection_translation
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "T", (2, 8))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    refs = (
        DrawingObjectRef("geometry", line.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
        DrawingObjectRef("text", text.text_id),
    )
    group = DrawingGroup(uuid4().hex, refs)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_translation(session.snapshot, (refs[0],), draft.frame, (0, 3)))
    assert session.snapshot.sketches[0].entities == (
        replace(line, start_mm=(0, 3), end_mm=(10, 3)),
    )
    assert session.snapshot.sketches[1].entities == (replace(circle, center_mm=(5, 5)),)
    assert session.snapshot.cross_tangencies == (relation,)
    assert session.snapshot.texts == (replace(text, position_mm=(2, 11)),)
    session.commit()
    path = tmp_path / "tangent-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.drawing_texts == (replace(text, position_mm=(2, 11)),)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (first, second)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.drawing_texts == (text,)


def test_group_move_preserves_cross_tangency_and_attached_datum() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    commands = loaded.document.commands
    with pytest.raises(ValidationError, match="相切"):
        app.move_tolerance_selection(
            services, loaded, (line.entity_id,), (), (), (), (0, 3), session_identity=1
        )
    assert loaded.document.commands == commands and services.kernel.sketches == (first, second)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (0, 0),
        attachment=DatumAttachment(
            first.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    refs = (
        DrawingObjectRef("geometry", line.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
        DrawingObjectRef("datum", datum.datum_id),
    )
    group = DrawingGroup(uuid4().hex, refs)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(session.prepare_attached_move((refs[0],), draft.frame, (0, 3)))
    assert session.snapshot.cross_tangencies == (relation,)
    assert session.snapshot.datums[0].position_mm == (2, 7)
    assert session.snapshot.datums[0].target_mm == (0, 3)
    assert session.snapshot.sketches[0].entities == (
        replace(line, start_mm=(0, 3), end_mm=(10, 3)),
    )
    assert session.snapshot.sketches[1].entities == (replace(circle, center_mm=(5, 5)),)
    session.undo()
    assert session.snapshot.sketches[:2] == (first, second)
    assert session.snapshot.cross_tangencies == (relation,) and session.snapshot.datums == (datum,)
    session.cancel()
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    app.move_tolerance_selection(
        services,
        loaded,
        (line.entity_id, circle.entity_id),
        (),
        (datum.datum_id,),
        (),
        (0, 3),
        session_identity=1,
    )
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (0, 3)
    loaded.bus.undo_operation()
    assert services.kernel.sketches == (first, second)
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("curve_kind", ["line", "polyline", "curved_polyline"])
@pytest.mark.parametrize("operation", ["rotate", "scale", "mirror"])
def test_group_affine_preserves_fully_selected_cross_sketch_tangency(
    tmp_path: Path, operation: str, curve_kind: str
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_transactions import (
        prepare_collection_mirror,
        prepare_collection_rotation,
        prepare_collection_scale,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_edit import mirror_entities, rotate_entities, scale_entities

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = (
        LineEntity(uuid4().hex, (0, 0), (10, 0))
        if curve_kind == "line"
        else PolylineEntity(
            uuid4().hex,
            ((0, 0), (10, 0), (10, 10)),
            bulges=(0.2, 0) if curve_kind == "curved_polyline" else (),
        )
    )
    circle = CircleEntity(uuid4().hex, (5, -3) if curve_kind == "curved_polyline" else (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id, 0 if curve_kind != "line" else None),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "external" if curve_kind == "curved_polyline" else "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    refs = (
        DrawingObjectRef("geometry", line.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
    )
    group = DrawingGroup(uuid4().hex, refs)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    if operation == "rotate":
        command = prepare_collection_rotation(session.snapshot, (refs[0],), draft.frame, (0, 0), 90)
        transformed = rotate_entities(
            (line, circle), (line.entity_id, circle.entity_id), (0, 0), 90
        )
    elif operation == "scale":
        command = prepare_collection_scale(session.snapshot, (refs[0],), draft.frame, (0, 0), 2)
        transformed = scale_entities((line, circle), (line.entity_id, circle.entity_id), (0, 0), 2)
    else:
        command = prepare_collection_mirror(
            session.snapshot, (refs[0],), draft.frame, (0, 0), (1, 0)
        )
        transformed = mirror_entities(
            (line, circle), (line.entity_id, circle.entity_id), (0, 0), (1, 0)
        )
    session.stage(command)
    assert session.snapshot.sketches[0].entities == (transformed[0],)
    assert session.snapshot.sketches[1].entities == (transformed[1],)
    expected = (
        replace(relation, branch="line_right")
        if operation == "mirror" and curve_kind != "curved_polyline"
        else relation
    )
    assert session.snapshot.cross_tangencies == (expected,)
    session.commit()
    path = tmp_path / f"group-tangency-{operation}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.cross_sketch_tangencies == (expected,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (first, second)
    assert services.kernel.cross_sketch_tangencies == (relation,)


@pytest.mark.parametrize("operation", ["rotate", "scale", "mirror"])
def test_group_affine_preserves_rectangle_segment_tangencies(
    tmp_path: Path, operation: str
) -> None:
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.drawing_transactions import (
        prepare_collection_mirror,
        prepare_collection_rotation,
        prepare_collection_scale,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, RectangleEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, -20))
    circle = CircleEntity(uuid4().hex, (5, -5), 5)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    pairs = tuple(
        (
            SketchGeometryReference(rectangle.entity_id, "segment", index),
            SketchGeometryReference(circle.entity_id, "geometry"),
        )
        for index in (0, 3)
    )
    relations = app.draft_cross_relations((first,), second, pairs)
    for relation in relations:
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    refs = (
        DrawingObjectRef("geometry", rectangle.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
    )
    session.stage(
        ReplayAppend(
            "drawing.group.create", 1, DrawingGroup(uuid4().hex, refs).to_mapping(), "local"
        )
    )
    if operation == "rotate":
        command = prepare_collection_rotation(session.snapshot, (refs[0],), draft.frame, (0, 0), 45)
    elif operation == "scale":
        command = prepare_collection_scale(session.snapshot, (refs[0],), draft.frame, (0, 0), 2)
    else:
        command = prepare_collection_mirror(
            session.snapshot, (refs[0],), draft.frame, (0, 0), (1, 0)
        )
    session.stage(command)
    result = session.snapshot.cross_tangencies
    assert {item.relation_id for item in result} == {item.relation_id for item in relations}
    validate_tangency_component(session.snapshot.sketches, result, first.sketch_id)
    session.commit()
    path = tmp_path / f"rectangle-tangency-{operation}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.cross_sketch_tangencies == result
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (first, second)
    assert {item.relation_id: item for item in services.kernel.cross_sketch_tangencies} == {
        item.relation_id: item for item in relations
    }


@pytest.mark.parametrize("operation", ["rotate", "scale", "mirror"])
def test_group_affine_rejects_partially_selected_cross_sketch_tangency(operation: str) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_transactions import (
        prepare_collection_mirror,
        prepare_collection_rotation,
        prepare_collection_scale,
    )
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    line_ref = DrawingObjectRef("geometry", line.entity_id, first.sketch_id)
    checkpoint, commands = session.checkpoint(), loaded.document.commands
    with pytest.raises(ValidationError, match="相切"):
        if operation == "rotate":
            prepare_collection_rotation(session.snapshot, (line_ref,), draft.frame, (0, 0), 90)
        elif operation == "scale":
            prepare_collection_scale(session.snapshot, (line_ref,), draft.frame, (0, 0), 2)
        else:
            prepare_collection_mirror(session.snapshot, (line_ref,), draft.frame, (0, 0), (1, 0))
    assert session.checkpoint() == checkpoint and loaded.document.commands == commands
    assert services.kernel.sketches == (first, second)
    session.cancel()


def test_group_mirror_tangency_across_rotated_coplanar_frames() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_transactions import prepare_collection_mirror
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    line = LineEntity(uuid4().hex, (0, 0), (0, -10))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, frame, (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    refs = (
        DrawingObjectRef("geometry", line.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
    )
    session.stage(
        ReplayAppend(
            "drawing.group.create", 1, DrawingGroup(uuid4().hex, refs).to_mapping(), "local"
        )
    )
    session.stage(
        prepare_collection_mirror(session.snapshot, (refs[0],), draft.frame, (0, 0), (1, 0))
    )
    assert session.snapshot.sketches[0].entities == (line,)
    assert session.snapshot.sketches[1].entities == (replace(circle, center_mm=(5, -2)),)
    assert session.snapshot.cross_tangencies == (replace(relation, branch="line_right"),)
    session.undo()
    assert session.snapshot.sketches[:2] == (
        first,
        second,
    ) and session.snapshot.cross_tangencies == (relation,)
    session.cancel()


@pytest.mark.parametrize(("complete", "simple"), [(False, False), (True, False), (True, True)])
def test_group_copy_cross_sketch_tangency_only_when_both_sides_copied(
    tmp_path: Path, complete: bool, simple: bool
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_transactions import (
        prepare_collection_copy,
        prepare_simple_collection_copy,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    refs = (
        DrawingObjectRef("geometry", line.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
    )
    group = DrawingGroup(uuid4().hex, refs, selectable=complete)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    prepare = prepare_simple_collection_copy if simple else prepare_collection_copy
    session.stage(prepare(session.snapshot, (refs[0],), draft.frame, (0, 4)))
    copies = session.snapshot.cross_tangencies
    assert relation in copies
    if complete:
        assert len(copies) == 2 and len(session.snapshot.groups) == 2
        duplicate = next(item for item in copies if item.relation_id != relation.relation_id)
        new_refs = session.snapshot.groups[-1].members
        assert {
            (duplicate.first.sketch_id, duplicate.first.entity_id),
            (duplicate.second.sketch_id, duplicate.second.entity_id),
        } == {(item.sketch_id, item.object_id) for item in new_refs}
        assert duplicate.branch == relation.branch
    else:
        assert copies == (relation,) and session.snapshot.groups == (group,)
    session.commit()
    path = tmp_path / "tangent-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.cross_sketch_tangencies == copies
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (first, second)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.drawing_groups == (group,)


def test_partial_group_copy_omits_external_local_constraint_without_changing_source() -> None:
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (2, 0), (2, 3))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (relation,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 9, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in (first, second)
    )
    group = DrawingGroup(uuid4().hex, refs, selectable=False)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_copy(session.snapshot, (refs[0],), draft.frame, (0, 4)))
    copied = session.snapshot.sketches[-1]
    assert copied.entities[:2] == (first, second) and len(copied.entities) == 3
    assert copied.constraints == (relation,) and session.snapshot.groups == (group,)
    session.undo()
    assert session.snapshot.sketches[-1] == draft and session.snapshot.groups == (group,)
    session.cancel()


def test_copy_geometry_does_not_require_unselected_dimension_layer_unlocked() -> None:
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 2),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    layers = services.kernel.drawing_layers
    locked = layers.replace(replace(layers.get("DIM"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, saved.sketch_id)
    before = session.snapshot.sketches[0]
    session.stage(prepare_collection_copy(session.snapshot, (ref,), draft.frame, (0, 4)))
    assert session.snapshot.sketches[0].constraints == (dimension,)
    assert len(session.snapshot.sketches[0].entities) == 2
    session.undo()
    assert session.snapshot.sketches[0] == before
    dimension_ref = DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, dimension_ref))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    checkpoint = session.checkpoint()
    with pytest.raises(ValidationError, match="尺寸|图层"):
        prepare_collection_copy(session.snapshot, (ref,), draft.frame, (0, 4))
    assert session.checkpoint() == checkpoint and session.snapshot.sketches[0] == before
    session.cancel()


def test_group_copy_cross_tangency_with_dimension_uses_new_sketch_identities() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    refs = (
        DrawingObjectRef("geometry", line.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
        DrawingObjectRef("dimension", dimension.constraint_id, first.sketch_id),
    )
    group = DrawingGroup(uuid4().hex, refs)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_copy(session.snapshot, (refs[0],), draft.frame, (0, 4)))
    duplicate_group = session.snapshot.groups[-1]
    duplicate = next(
        item
        for item in session.snapshot.cross_tangencies
        if item.relation_id != relation.relation_id
    )
    geometry = tuple(item for item in duplicate_group.members if item.kind == "geometry")
    assert {duplicate.first.sketch_id, duplicate.second.sketch_id} == {
        item.sketch_id for item in geometry
    }
    assert first.sketch_id not in {item.sketch_id for item in geometry}
    assert second.sketch_id not in {item.sketch_id for item in geometry}
    copied_dimension = next(item for item in duplicate_group.members if item.kind == "dimension")
    copied_line = next(item for item in geometry if item.sketch_id == copied_dimension.sketch_id)
    copied_sketch = next(
        item for item in session.snapshot.sketches if item.sketch_id == copied_line.sketch_id
    )
    assert copied_sketch.constraints[0].references[0].entity_id == copied_line.object_id
    session.undo()
    assert session.snapshot.groups == (group,) and session.snapshot.cross_tangencies == (relation,)
    session.cancel()


def test_unrelated_cross_sketch_tangency_does_not_block_move() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    independent = LineEntity(uuid4().hex, (0, 8), (10, 8))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (independent,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    unrelated = DrawingObjectRef("geometry", independent.entity_id, draft.sketch_id)
    session.stage(
        prepare_simple_collection_move(session.snapshot, (unrelated,), draft.frame, (0, 1))
    )
    assert session.snapshot.cross_tangencies == (relation,)
    with pytest.raises(ValidationError, match="相切"):
        prepare_simple_collection_move(
            session.snapshot,
            (DrawingObjectRef("geometry", line.entity_id, first.sketch_id),),
            draft.frame,
            (0, 1),
        )
    session.cancel()


def test_mixed_annotation_picture_group_copy_reopens_as_one_operation(tmp_path: Path) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        decode_collection_clipboard,
        encode_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.drawing_text import DrawingText
    from mycad.core.drawing_transactions import (
        prepare_collection_copy,
        prepare_collection_delete,
        prepare_collection_translation,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    sample = (
        Path(__file__).resolve().parents[2]
        / "docs/examples/drawing-collections/mixed-annotations-image.my2d"
    )
    services = app.build_app(discoverers=[])
    loaded = app.open_app_document(services, sample)
    group = services.kernel.drawing_groups[0]
    source_sketch = services.kernel.sketches[0]
    source_line = source_sketch.entities[0]
    assert isinstance(source_line, LineEntity)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(source_line.entity_id, "geometry"),),
        40,
        "mm",
        position_mm=(20, 5),
    )
    solved = services.kernel.preview_sketch_constraint(source_sketch, dimension)
    assert solved.status == "success"
    loaded.bus.execute(
        "sketch.constraint.add",
        solved.command_params(source_sketch, dimension, local_frame=True),
        "local",
        version=7,
    )
    text = DrawingText(uuid4().hex, "Label", (3, 8))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    definition = BlockDefinition(
        uuid4().hex, "GroupSymbol", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (9, 9), 30, 2)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = replace(
        group,
        members=(
            *group.members,
            DrawingObjectRef("text", text.text_id),
            DrawingObjectRef("dimension", dimension.constraint_id, source_sketch.sketch_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
    )
    loaded.bus.execute("drawing.group.update", group.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    seed = next(item for item in group.members if item.kind == "geometry")
    move = prepare_collection_translation(before, (seed,), WorkPlaneFrame.xy(), (0, 12))
    assert app.drawing_collection_snapshot(services) == before
    loaded.bus.execute(move.command_id, move.params, "local", version=move.version)
    moved = app.drawing_collection_snapshot(services)
    moved_sketch = next(
        item for item in moved.sketches if item.sketch_id == source_sketch.sketch_id
    )
    moved_line = moved_sketch.entities[0]
    assert isinstance(moved_line, LineEntity)
    assert moved_line.start_mm == pytest.approx((0, 12))
    assert moved_sketch.constraints[0].references[0].entity_id == source_line.entity_id
    assert moved_sketch.constraints[0].position_mm == pytest.approx((20, 17))
    assert moved.texts[0].position_mm == pytest.approx((3, 20))
    assert moved.rasters[0].origin_mm == pytest.approx(
        (before.rasters[0].origin_mm[0], before.rasters[0].origin_mm[1] + 12)
    )
    assert moved.frames[0].position_mm == pytest.approx(
        (before.frames[0].position_mm[0], before.frames[0].position_mm[1] + 12)
    )
    assert moved.datums[0].position_mm == pytest.approx(
        (before.datums[0].position_mm[0], before.datums[0].position_mm[1] + 12)
    )
    assert moved.reference_dimensions[0].first_mm == pytest.approx(
        (
            before.reference_dimensions[0].first_mm[0],
            before.reference_dimensions[0].first_mm[1] + 12,
        )
    )
    assert moved.block_instances[0].insertion_mm == pytest.approx((9, 21))
    move_path = tmp_path / "mixed-annotation-move.my2d"
    save_document(loaded.document, move_path)
    loaded = app.open_app_document(services, move_path)
    assert app.drawing_collection_snapshot(services) == moved
    loaded.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    loaded.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == moved
    loaded.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    operation = prepare_collection_copy(before, (seed,), WorkPlaneFrame.xy(), (0, 20))
    assert app.drawing_collection_snapshot(services) == before
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    copied = app.drawing_collection_snapshot(services)
    assert len(copied.groups) == 2
    assert {item.kind for item in copied.groups[-1].members} == {
        "geometry",
        "dimension",
        "text",
        "raster",
        "tolerance",
        "datum",
        "reference_dimension",
        "block_instance",
    }
    assert not set(group.members).intersection(copied.groups[-1].members)
    copied_geometry = next(item for item in copied.groups[-1].members if item.kind == "geometry")
    copied_dimension = next(item for item in copied.groups[-1].members if item.kind == "dimension")
    copied_sketch = next(
        item for item in copied.sketches if item.sketch_id == copied_geometry.sketch_id
    )
    assert copied_dimension.sketch_id == copied_sketch.sketch_id
    assert copied_sketch.constraints[0].constraint_id == copied_dimension.object_id
    assert copied_sketch.constraints[0].references[0].entity_id == copied_geometry.object_id
    assert copied_sketch.constraints[0].position_mm == pytest.approx((20, 25))
    assert all(
        len(items) == 2
        for items in (
            copied.texts,
            copied.rasters,
            copied.frames,
            copied.datums,
            copied.reference_dimensions,
            copied.block_instances,
        )
    )
    assert copied.rasters[-1].origin_mm == pytest.approx(
        (before.rasters[0].origin_mm[0], before.rasters[0].origin_mm[1] + 20)
    )
    assert copied.frames[-1].position_mm == pytest.approx(
        (before.frames[0].position_mm[0], before.frames[0].position_mm[1] + 20)
    )
    assert copied.datums[-1].position_mm == pytest.approx(
        (before.datums[0].position_mm[0], before.datums[0].position_mm[1] + 20)
    )
    assert copied.texts[-1].position_mm == pytest.approx((3, 28))
    assert copied.block_definitions == (definition,)
    assert copied.block_instances[-1].definition_id == definition.definition_id
    assert copied.block_instances[-1].instance_id != instance.instance_id
    assert copied.block_instances[-1].insertion_mm == pytest.approx((9, 29))
    assert copied.block_instances[-1].rotation_deg == instance.rotation_deg
    assert copied.block_instances[-1].scale == instance.scale
    old_reference, new_reference = before.reference_dimensions[0], copied.reference_dimensions[-1]
    assert new_reference.first_mm == pytest.approx(
        (old_reference.first_mm[0], old_reference.first_mm[1] + 20)
    )
    assert copied.datums[-1].label != before.datums[0].label
    path = tmp_path / "mixed-annotation-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert app.drawing_collection_snapshot(services) == copied
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == copied
    for layer in (
        SketchLayer("Blocked", locked=True),
        SketchLayer("Blocked", visible=False),
        SketchLayer("Blocked", frozen=True),
    ):
        blocked = replace(
            copied,
            layers=copied.layers.add(layer),
            block_instances=(
                copied.block_instances[0],
                replace(copied.block_instances[1], layer_name="Blocked"),
            ),
        )
        with pytest.raises(ValidationError):
            prepare_collection_delete(blocked, (copied_geometry,))
        assert app.drawing_collection_snapshot(services) == copied
    deletion = prepare_collection_delete(copied, (copied_geometry,))
    reopened.bus.execute(deletion.command_id, deletion.params, "local", version=deletion.version)
    deleted = app.drawing_collection_snapshot(services)
    assert deleted.groups == (group,)
    assert deleted.texts == before.texts and deleted.rasters == before.rasters
    assert deleted.frames == before.frames and deleted.datums == before.datums
    assert deleted.reference_dimensions == before.reference_dimensions
    assert deleted.block_definitions == before.block_definitions
    assert deleted.block_instances == before.block_instances
    assert all(
        item.entity_id != copied_geometry.object_id
        for sketch in deleted.sketches
        for item in sketch.entities
    )
    assert all(
        item.constraint_id != copied_dimension.object_id
        for sketch in deleted.sketches
        for item in sketch.constraints
    )
    deletion_path = tmp_path / "mixed-annotation-delete.my2d"
    save_document(reopened.document, deletion_path)
    reopened_deletion = app.open_app_document(services, deletion_path)
    assert app.drawing_collection_snapshot(services) == deleted
    reopened_deletion.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == copied
    reopened_deletion.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == deleted
    payload = decode_collection_clipboard(
        encode_collection_clipboard(capture_collection_clipboard(deleted, (seed,)))
    )
    target = app.new_workspace_document(services, kind="sketch")
    conflict = BlockDefinition(
        uuid4().hex, definition.name, (LineEntity(uuid4().hex, (0, 0), (5, 0)),), ()
    )
    target.bus.execute("drawing.block.create", conflict.to_mapping(), "local")
    target_before = app.drawing_collection_snapshot(services)
    paste = prepare_collection_paste(payload, target_before, (10, 0))
    target.bus.execute(paste.command_id, paste.params, "local", version=paste.version)
    pasted = app.drawing_collection_snapshot(services)
    assert len(pasted.groups) == 1
    assert {item.kind for item in pasted.groups[0].members} == {
        "geometry",
        "dimension",
        "text",
        "raster",
        "tolerance",
        "datum",
        "reference_dimension",
        "block_instance",
    }
    assert not set(group.members).intersection(pasted.groups[0].members)
    assert pasted.block_definitions[0] == conflict
    pasted_definition = pasted.block_definitions[-1]
    assert pasted_definition.name != definition.name
    assert pasted_definition.definition_id != definition.definition_id
    assert pasted.block_instances[0].definition_id == pasted_definition.definition_id
    assert pasted.block_instances[0].insertion_mm == pytest.approx((19, 9))
    pasted_geometry = next(item for item in pasted.groups[0].members if item.kind == "geometry")
    pasted_dimension = next(item for item in pasted.groups[0].members if item.kind == "dimension")
    pasted_sketch = next(
        item for item in pasted.sketches if item.sketch_id == pasted_geometry.sketch_id
    )
    assert pasted_sketch.constraints[0].constraint_id == pasted_dimension.object_id
    assert pasted_sketch.constraints[0].references[0].entity_id == pasted_geometry.object_id
    assert pasted.rasters[0].png_base64 == before.rasters[0].png_base64
    paste_path = tmp_path / "mixed-annotation-cross-document.my2d"
    save_document(target.document, paste_path)
    reopened_paste = app.open_app_document(services, paste_path)
    assert app.drawing_collection_snapshot(services) == pasted
    reopened_paste.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == target_before
    reopened_paste.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == pasted


def test_mixed_geometry_text_picture_group_moves_atomically(tmp_path: Path) -> None:
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_text import DrawingText
    from mycad.core.drawing_transactions import prepare_collection_translation
    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "A", (2, 1))
    picture = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (3, 2),
        2,
        2,
    )
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    session.stage(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [picture.to_mapping(version=2)]},
            "local",
        )
    )
    geometry = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            geometry,
            DrawingObjectRef("text", text.text_id),
            DrawingObjectRef("raster", picture.image_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    locked = replace(
        session.snapshot,
        texts=(replace(text, layer_name="Locked"),),
        layers=session.snapshot.layers.add(SketchLayer("Locked", locked=True)),
    )
    with pytest.raises(ValidationError, match="锁定"):
        prepare_collection_translation(locked, (geometry,), draft.frame, (0, 3))
    assert session.snapshot.texts == (text,)
    assert session.snapshot.sketches[-1].entities == (line,)
    session.stage(
        prepare_collection_translation(session.snapshot, (geometry,), draft.frame, (0, 3))
    )
    assert session.snapshot.sketches[-1].entities == (
        replace(line, start_mm=(0, 3), end_mm=(2, 3)),
    )
    assert session.snapshot.texts == (replace(text, position_mm=(2, 4)),)
    assert session.snapshot.rasters == (replace(picture, origin_mm=(3, 5)),)
    session.commit()
    path = tmp_path / "mixed-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (line,)
    assert services.kernel.drawing_texts == (text,)
    assert services.kernel.drawing_rasters == (picture,)
    assert services.kernel.drawing_groups == (group,)


def test_mixed_group_copy_freezes_all_identities_and_undoes_after_reopen(tmp_path: Path) -> None:
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_text import DrawingText
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "A", (2, 1))
    picture = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (3, 2),
        2,
        2,
    )
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    session.stage(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [picture.to_mapping(version=2)]},
            "local",
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (ref, DrawingObjectRef("text", text.text_id), DrawingObjectRef("raster", picture.image_id)),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_copy(session.snapshot, (ref,), draft.frame, (0, 3)))
    assert len(session.snapshot.groups) == 2
    copied = session.snapshot.groups[-1]
    assert len(session.snapshot.sketches[-1].entities) == 2
    assert len(session.snapshot.texts) == len(session.snapshot.rasters) == 2
    session.commit()
    path = tmp_path / "mixed-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.sketches[-1].entities == (line,)
    assert services.kernel.drawing_texts == (text,)
    assert services.kernel.drawing_rasters == (picture,)
    reopened.bus.redo_operation()
    assert services.kernel.drawing_groups[-1] == copied


def test_group_copy_allocates_point_ids_for_legacy_curve(tmp_path: Path) -> None:
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    curve = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", curve.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_copy(session.snapshot, (ref,), draft.frame, (5, 0)))
    original, copied = session.snapshot.sketches[-1].entities
    assert original == curve
    assert isinstance(copied, PolylineEntity) and len(copied.point_ids) == 3
    assert copied.entity_id != curve.entity_id
    session.commit()
    path = tmp_path / "legacy-group-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[-1].entities == (curve, copied)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (curve,)
    reopened.bus.redo_operation()
    assert services.kernel.sketches[-1].entities == (curve, copied)


def test_group_copy_rebinds_legacy_curve_vertex_datum_with_new_point_ids() -> None:
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    curve = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (2, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(curve.entity_id, "vertex", 1)
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", curve.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("datum", datum.datum_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_copy(session.snapshot, (ref,), draft.frame, (0, 3)))
    copied = session.snapshot.sketches[-1].entities[-1]
    assert isinstance(copied, PolylineEntity) and len(copied.point_ids) == 3
    attachment = session.snapshot.datums[-1].attachment
    assert attachment is not None and attachment.reference.entity_id == copied.entity_id
    assert attachment.reference.index == 1
    assert session.snapshot.datums[-1].target_mm == (2, 3)
    session.cancel()


def test_group_translation_moves_free_tolerance_datum_and_reference(tmp_path: Path) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_transactions import prepare_collection_translation
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (5, 5))
    datum = DatumIdentifier(uuid4().hex, "A", (8, 5), (7, 4))
    reference = DetachedDimension(uuid4().hex, "aligned", (0, 2), (2, 2), (1, 3), 0, 2)
    session.stage(
        ReplayAppend(
            "drawing.tolerance.batch",
            28,
            {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
            "local",
        )
    )
    session.stage(
        ReplayAppend(
            "drawing.reference_dimensions.batch", 10, {"add": [reference.to_mapping()]}, "local"
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            ref,
            DrawingObjectRef("tolerance", frame.frame_id),
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("reference_dimension", reference.dimension_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_translation(session.snapshot, (ref,), draft.frame, (0, 3)))
    assert session.snapshot.frames[0].position_mm == (5, 8)
    assert session.snapshot.datums[0].position_mm == (8, 8)
    assert session.snapshot.datums[0].target_mm == (7, 7)
    assert session.snapshot.reference_dimensions[0].first_mm == (0, 5)
    session.commit()
    path = tmp_path / "annotations.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_reference_dimensions == (reference,)
    assert services.kernel.sketches[-1].entities == (line,)


def test_group_translation_refuses_attached_datum_without_partial_change() -> None:
    from mycad.core.drawing_transactions import prepare_collection_translation
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("datum", datum.datum_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    with pytest.raises(ValidationError, match="附着"):
        prepare_collection_translation(session.snapshot, (ref,), draft.frame, (0, 3))
    assert session.snapshot.sketches[-1].entities == (line,)
    assert session.snapshot.datums == (datum,)
    assert session.snapshot.groups == (group,)
    assert loaded.document.commands == ()
    session.cancel()


def test_attached_datum_and_group_geometry_move_once_in_candidate(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("datum", datum.datum_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(session.prepare_attached_move((ref,), draft.frame, (0, 3)))
    moved = session.snapshot.datums[0]
    assert moved.position_mm == (4, 7)
    assert moved.target_mm == (0, 3)
    assert moved.attachment == datum.attachment
    assert loaded.document.commands == ()
    session.commit()
    path = tmp_path / "attached-datum.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.sketches[-1].entities == (line,)
    assert services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("both", [False, True])
def test_attached_group_move_distinguishes_same_id_in_different_sketches(
    tmp_path: Path, both: bool
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    other = replace(line, start_mm=(0, 8), end_mm=(2, 8))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            saved.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", line.entity_id, saved.sketch_id)
    members = (ref, DrawingObjectRef("datum", datum.datum_id))
    if both:
        members += (DrawingObjectRef("geometry", other.entity_id, draft.sketch_id),)
    group = DrawingGroup(uuid4().hex, members)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(session.prepare_attached_move((ref,), WorkPlaneFrame.xy(), (0, 3)))
    after = session.snapshot
    assert after.sketches[0].entities == (replace(line, start_mm=(0, 3), end_mm=(2, 3)),)
    assert after.sketches[-1].entities == (
        replace(other, start_mm=(0, 11), end_mm=(2, 11)) if both else other,
    )
    assert after.datums == (replace(datum, position_mm=(4, 7), target_mm=(0, 3)),)
    assert after.groups == (group,)
    session.undo()
    assert session.snapshot == before
    session.redo()
    assert session.snapshot == after
    session.commit()
    path = tmp_path / "same-id-sketches.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    history = tuple(reopened.document.commands)
    with pytest.raises(ValidationError, match="身份不唯一"):
        app.move_tolerance_selection(
            services, reopened, (line.entity_id,), (), (), (), (0, 3), session_identity=1
        )
    assert tuple(reopened.document.commands) == history
    assert app.drawing_collection_snapshot(services) == before


def test_attached_group_move_projects_displacement_into_rotated_sketch(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        2,
        "mm",
        position_mm=(1, 2),
        text_position_mm=(1, 3),
    )
    draft = Sketch(uuid4().hex, frame, (line,), (dimension,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            ref,
            DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(session.prepare_attached_move((ref,), WorkPlaneFrame.xy(), (3, 0)))
    after = session.snapshot
    assert after.sketches[-1].entities == (replace(line, start_mm=(0, -3), end_mm=(2, -3)),)
    assert after.sketches[-1].constraints == (
        replace(dimension, position_mm=(1, -1), text_position_mm=(1, 0)),
    )
    assert after.datums == (replace(datum, position_mm=(7, 4), target_mm=(3, 0)),)
    assert after.groups == (group,)
    session.undo()
    assert session.snapshot == before
    session.redo()
    assert session.snapshot == after
    session.commit()
    path = tmp_path / "rotated-attached-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_attached_group_move_allows_cross_type_id_collision(tmp_path: Path) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(line.entity_id, "文字", (8, 8))
    datum = DatumIdentifier(
        line.entity_id,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (ref, DrawingObjectRef("text", text.text_id), DrawingObjectRef("datum", datum.datum_id)),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(session.prepare_attached_move((ref,), draft.frame, (0, 3)))
    after = session.snapshot
    assert after.sketches[-1].entities == (replace(line, start_mm=(0, 3), end_mm=(2, 3)),)
    assert after.texts == (replace(text, position_mm=(8, 11)),)
    assert after.datums == (replace(datum, position_mm=(4, 7), target_mm=(0, 3)),)
    assert after.groups == (group,)
    session.undo()
    assert session.snapshot == before
    session.redo()
    assert session.snapshot == after
    session.commit()
    path = tmp_path / "attached-collision.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_attached_move_rejects_unselected_annotation_without_changing_candidate() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    before = session.snapshot
    with pytest.raises(ValidationError, match="未选中"):
        session.prepare_attached_move(
            (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),), draft.frame, (0, 3)
        )
    assert session.snapshot == before
    assert loaded.document.commands == ()
    session.cancel()


def test_unrelated_attached_datum_does_not_block_group_move() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (0, 5), (2, 5))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 9),
        (0, 5),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(second.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", first.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(session.prepare_attached_move((ref,), draft.frame, (0, 3)))
    assert session.snapshot.sketches[-1].entities == (
        replace(first, start_mm=(0, 3), end_mm=(2, 3)),
        second,
    )
    assert session.snapshot.datums == (datum,)
    session.cancel()


def test_unrelated_attachment_allows_mixed_group_with_cross_type_id_collision(
    tmp_path: Path,
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (0, 5), (2, 5))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(first.entity_id, "A", (4, 0))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 9),
        (0, 5),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(second.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", first.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("text", text.text_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(session.prepare_attached_move((ref,), draft.frame, (0, 3)))
    after = session.snapshot
    assert after.sketches[-1].entities == (
        replace(first, start_mm=(0, 3), end_mm=(2, 3)),
        second,
    )
    assert after.texts == (replace(text, position_mm=(4, 3)),)
    assert after.datums == (datum,) and after.groups == (group,)
    session.undo()
    assert session.snapshot == before
    session.redo()
    assert session.snapshot == after
    session.commit()
    path = tmp_path / "cross-type-unrelated-attachment.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_group_copy_rebinds_attached_datum_to_copied_geometry(tmp_path: Path) -> None:
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("datum", datum.datum_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_copy(session.snapshot, (ref,), draft.frame, (0, 3)))
    duplicate_group = session.snapshot.groups[-1]
    duplicate_ref = next(item for item in duplicate_group.members if item.kind == "geometry")
    duplicate = session.snapshot.datums[-1]
    assert duplicate.attachment is not None
    assert duplicate.attachment.sketch_id == duplicate_ref.sketch_id
    assert duplicate.attachment.reference.entity_id == duplicate_ref.object_id
    assert duplicate.target_mm == (0, 3) and duplicate.position_mm == (4, 7)
    session.undo()
    assert session.snapshot.datums == (datum,)
    assert session.snapshot.groups == (group,)
    session.redo()
    session.commit()
    path = tmp_path / "attached-group-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)
    reopened.bus.redo_operation()
    assert services.kernel.drawing_groups[-1] == duplicate_group
    assert services.kernel.drawing_datum_identifiers[-1] == duplicate


def test_group_copy_rebinds_attached_datums_across_copied_sketches() -> None:
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (0, 5), (2, 5))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(first.entity_id, "geometry"),), 2, "mm"
    )
    first_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,), (dimension,))
    second_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second,))
    app.commit_new_sketch(services, loaded, first_sketch, session_identity=1)
    app.commit_new_sketch(services, loaded, second_sketch, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    datums = tuple(
        DatumIdentifier(
            uuid4().hex,
            label,
            (4, y + 3),
            (0, y),
            attachment=DatumAttachment(
                sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
            ),
        )
        for label, y, sketch, line in (
            ("A", 0, first_sketch, first),
            ("B", 5, second_sketch, second),
        )
    )
    session.stage(
        ReplayAppend(
            "drawing.tolerance.batch",
            28,
            {"add_datums": [item.to_mapping() for item in datums]},
            "local",
        )
    )
    refs = (
        DrawingObjectRef("geometry", first.entity_id, first_sketch.sketch_id),
        DrawingObjectRef("geometry", second.entity_id, second_sketch.sketch_id),
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            *refs,
            DrawingObjectRef("dimension", dimension.constraint_id, first_sketch.sketch_id),
            *(DrawingObjectRef("datum", item.datum_id) for item in datums),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_copy(session.snapshot, (refs[0],), draft.frame, (0, 3)))
    copied = session.snapshot
    copied_geometries = {
        item.object_id: item for item in copied.groups[-1].members if item.kind == "geometry"
    }
    copied_datums = copied.datums[-2:]
    assert (
        len({item.attachment.sketch_id for item in copied_datums if item.attachment is not None})
        == 2
    )
    for datum in copied_datums:
        assert datum.attachment is not None
        assert datum.attachment.reference.entity_id in copied_geometries
        assert (
            datum.attachment.sketch_id
            == copied_geometries[datum.attachment.reference.entity_id].sketch_id
        )
    session.cancel()


def test_group_translation_moves_attached_dimension_once(tmp_path: Path) -> None:
    from mycad.core.drawing_transactions import prepare_collection_translation
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 2),
        text_position_mm=(5, 2.5),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 8), (2, 8)),))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, saved.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (ref, DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id))
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    layers = session.snapshot.layers.add(SketchLayer("Locked", locked=True))
    locked_dimension = replace(dimension, layer_name="Locked")
    locked_saved = replace(saved, constraints=(locked_dimension,), layers=layers)
    locked_snapshot = replace(session.snapshot, sketches=(locked_saved, draft), layers=layers)
    with pytest.raises(ValidationError, match="尺寸.*锁定"):
        prepare_collection_translation(locked_snapshot, (ref,), draft.frame, (0, 3))
    assert session.snapshot.sketches[0] == saved
    session.stage(prepare_collection_translation(session.snapshot, (ref,), draft.frame, (0, 3)))
    moved = session.snapshot.sketches[0]
    assert moved.entities == (replace(line, start_mm=(0, 3), end_mm=(10, 3)),)
    assert moved.constraints == (replace(dimension, position_mm=(5, 5), text_position_mm=(5, 5.5)),)
    session.commit()
    path = tmp_path / "dimension-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[0] == saved
    assert services.kernel.drawing_groups == (group,)


def test_group_copy_with_sketch_and_reference_dimensions() -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 10, "mm"
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    reference = DetachedDimension(uuid4().hex, "aligned", (0, 2), (2, 2), (1, 3), 0, 2)
    session.stage(
        ReplayAppend(
            "drawing.reference_dimensions.batch", 10, {"add": [reference.to_mapping()]}, "local"
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            ref,
            DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id),
            DrawingObjectRef("reference_dimension", reference.dimension_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_copy(session.snapshot, (ref,), draft.frame, (0, 3)))
    assert len(session.snapshot.groups) == 2
    assert session.snapshot.reference_dimensions[1].location_mm == (1, 6)
    assert len(session.snapshot.sketches[-1].constraints) == 1
    session.cancel()


def test_group_copy_preserves_selected_dimension_and_new_geometry(tmp_path: Path) -> None:
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 2),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 8), (2, 8)),))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, saved.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (ref, DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id))
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(prepare_collection_copy(session.snapshot, (ref,), draft.frame, (0, 3)))
    copied_group = session.snapshot.groups[-1]
    copied_geom = next(item for item in copied_group.members if item.kind == "geometry")
    copied_dim = next(item for item in copied_group.members if item.kind == "dimension")
    copied_sketch = next(
        item for item in session.snapshot.sketches if item.sketch_id == copied_geom.sketch_id
    )
    assert copied_dim.sketch_id == copied_sketch.sketch_id
    assert copied_sketch.entities[0].entity_id == copied_geom.object_id
    assert copied_sketch.constraints[0].constraint_id == copied_dim.object_id
    assert copied_sketch.constraints[0].references[0].entity_id == copied_geom.object_id
    assert copied_sketch.constraints[0].position_mm == (5, 5)
    session.commit()
    draft_line = draft.entities[0]
    assert isinstance(draft_line, LineEntity)
    revised_draft = replace(
        draft,
        entities=(replace(draft_line, start_mm=(0, 9), end_mm=(2, 9)),),
    )
    state = revised_draft.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": draft.sketch_id,
                    "base_state_sha256": draft.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=79,
    )
    assert services.kernel.drawing_groups[-1] == copied_group
    assert any(item.sketch_id == copied_sketch.sketch_id for item in services.kernel.sketches)
    loaded.bus.undo_operation()
    path = tmp_path / "dimension-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)
    assert all(item.sketch_id != copied_sketch.sketch_id for item in services.kernel.sketches)
    reopened.bus.redo_operation()
    assert services.kernel.drawing_groups[-1] == copied_group


def test_copy_overlapping_groups_clones_only_complete_memberships(tmp_path: Path) -> None:
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    lines = tuple(LineEntity(uuid4().hex, (0, y), (2, y)) for y in (0, 5, 10))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    refs = tuple(DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in lines)
    first = DrawingGroup(uuid4().hex, refs[:2], name="first")
    overlapping = DrawingGroup(uuid4().hex, refs[1:], name="overlap")
    disabled = DrawingGroup(uuid4().hex, (refs[1],), name="disabled", selectable=False)
    for group in (first, overlapping, disabled):
        session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(prepare_collection_copy(before, (refs[0],), draft.frame, (10, 0)))
    after = session.snapshot
    assert len(after.sketches[-1].entities) == 5
    copies = tuple(
        group
        for group in after.groups
        if group.group_id not in {first.group_id, overlapping.group_id, disabled.group_id}
    )
    assert {group.name for group in copies} == {"first 副本", "disabled 副本"}
    first_copy = next(group for group in copies if group.name == "first 副本")
    disabled_copy = next(group for group in copies if group.name == "disabled 副本")
    assert len(first_copy.members) == 2 and disabled_copy.members == (first_copy.members[1],)
    assert not disabled_copy.selectable
    assert session.undo() is None and session.snapshot == before
    assert session.redo() is None and session.snapshot == after
    assert loaded.document.commands == ()
    session.commit()
    path = tmp_path / "overlap-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


@pytest.mark.parametrize("operation", ["rotate", "scale", "mirror"])
def test_group_affine_preserves_or_removes_inferred_axis_relations(
    tmp_path: Path, operation: str
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.drawing_transactions import (
        prepare_collection_mirror,
        prepare_collection_rotation,
        prepare_collection_scale,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    selected = LineEntity(uuid4().hex, (1, 0), (3, 0))
    other = LineEntity(uuid4().hex, (0, 3), (2, 3))
    relation = SketchConstraint(
        uuid4().hex,
        "horizontal",
        (SketchGeometryReference(selected.entity_id, "geometry"),),
        source="inferred",
    )
    unrelated = replace(
        relation,
        constraint_id=uuid4().hex,
        references=(SketchGeometryReference(other.entity_id, "geometry"),),
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (selected, other), (relation, unrelated))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "group", (1, 1))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    ref = DrawingObjectRef("geometry", selected.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, DrawingObjectRef("text", text.text_id)))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    if operation == "rotate":
        command = prepare_collection_rotation(before, (ref,), draft.frame, (0, 0), 90)
    elif operation == "scale":
        command = prepare_collection_scale(before, (ref,), draft.frame, (0, 0), 2)
    else:
        command = prepare_collection_mirror(before, (ref,), draft.frame, (0, 0), (1, 1))
    session.stage(command)
    after = session.snapshot
    expected = (relation, unrelated) if operation == "scale" else (unrelated,)
    assert after.sketches[-1].constraints == expected
    assert after.groups == (group,) and after.texts[0] != text
    session.undo()
    assert session.snapshot == before
    session.redo()
    assert session.snapshot == after
    session.commit()
    path = tmp_path / f"inferred-{operation}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_copy_legacy_uuid_group_keeps_source_id_and_replays(tmp_path: Path) -> None:
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(str(uuid4()), (0, 0), (2, 0))
    draft = Sketch(str(uuid4()), WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(str(uuid4()), (ref,), name="Legacy")
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(prepare_collection_copy(before, (ref,), draft.frame, (5, 0)))
    after = session.snapshot
    copied = next(item for item in after.groups if item.group_id != group.group_id)
    assert after.groups[0] == group and copied.name == "Legacy 副本"
    assert len(copied.group_id) == 32 and len(copied.members[0].object_id) == 32
    assert copied.members[0] != ref
    session.commit()
    path = tmp_path / "legacy-group-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


@pytest.mark.parametrize("operation", ["rotate", "scale", "mirror"])
def test_group_affine_still_rejects_user_axis_constraints(operation: str) -> None:
    from mycad.core.drawing_transactions import (
        prepare_collection_mirror,
        prepare_collection_rotation,
        prepare_collection_scale,
    )
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    constraint = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(line.entity_id, "geometry"),)
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    checkpoint = session.checkpoint()
    with pytest.raises(ValidationError, match="约束"):
        if operation == "rotate":
            prepare_collection_rotation(before, (ref,), draft.frame, (0, 0), 90)
        elif operation == "scale":
            prepare_collection_scale(before, (ref,), draft.frame, (0, 0), 2)
        else:
            prepare_collection_mirror(before, (ref,), draft.frame, (0, 0), (1, 1))
    assert session.checkpoint() == checkpoint and session.snapshot == before
    assert loaded.document.commands == ()
    session.cancel()


@pytest.mark.parametrize("kind", ["coincident", "tangent"])
@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("operation", ["rotate", "scale", "mirror"])
def test_group_affine_keeps_only_satisfied_inferred_relations(
    tmp_path: Path, kind: Literal["coincident", "tangent"], complete: bool, operation: str
) -> None:
    from mycad.core.drawing_transactions import (
        prepare_collection_mirror,
        prepare_collection_rotation,
        prepare_collection_scale,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (-2, 0), (2, 0))
    if kind == "coincident":
        second = LineEntity(uuid4().hex, (2, 0), (2, 2))
        references = (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        )
    else:
        second = CircleEntity(uuid4().hex, (0, 1), 1)
        references = (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        )
    relation = SketchConstraint(uuid4().hex, kind, references, source="inferred")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (relation,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in (first, second)
    )
    group = DrawingGroup(uuid4().hex, refs if complete else refs[:1])
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    if operation == "rotate":
        command = prepare_collection_rotation(before, refs[:1], draft.frame, (0, 0), 90)
    elif operation == "scale":
        command = prepare_collection_scale(before, refs[:1], draft.frame, (0, 0), 2)
    else:
        command = prepare_collection_mirror(before, refs[:1], draft.frame, (0, 0), (1, 1))
    session.stage(command)
    after = session.snapshot
    keep = complete or (kind == "tangent" and operation == "scale")
    assert after.sketches[-1].constraints == ((relation,) if keep else ())
    assert after.groups == (group,)
    session.undo()
    assert session.snapshot == before
    session.redo()
    assert session.snapshot == after
    session.commit()
    path = tmp_path / f"inferred-{kind}-{complete}-{operation}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("operation", ["rotate", "mirror"])
def test_group_affine_rechecks_inferred_polyline_segment_tangency(
    tmp_path: Path, complete: bool, operation: str
) -> None:
    from mycad.core.drawing_transactions import (
        prepare_collection_mirror,
        prepare_collection_rotation,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = PolylineEntity(uuid4().hex, ((-2, 0), (2, 0), (3, 2)))
    circle = CircleEntity(uuid4().hex, (0, 1), 1)
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle), (relation,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in (line, circle)
    )
    group = DrawingGroup(uuid4().hex, refs if complete else refs[:1])
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    if operation == "rotate":
        command = prepare_collection_rotation(before, refs[:1], draft.frame, (0, 0), 90)
    else:
        command = prepare_collection_mirror(before, refs[:1], draft.frame, (0, 0), (1, 1))
    session.stage(command)
    after = session.snapshot
    assert after.sketches[-1].constraints == ((relation,) if complete else ())
    session.commit()
    path = tmp_path / f"polyline-{complete}-{operation}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


@pytest.mark.parametrize("kind", ["coincident", "tangent"])
@pytest.mark.parametrize("complete", [False, True])
def test_group_rotation_still_rejects_user_coincidence_and_tangency(
    kind: Literal["coincident", "tangent"], complete: bool
) -> None:
    from mycad.core.drawing_transactions import prepare_collection_rotation
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (-2, 0), (2, 0))
    if kind == "coincident":
        second = LineEntity(uuid4().hex, (2, 0), (2, 2))
        references = (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        )
    else:
        second = CircleEntity(uuid4().hex, (0, 1), 1)
        references = (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        )
    relation = SketchConstraint(uuid4().hex, kind, references)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (relation,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in (first, second)
    )
    group = DrawingGroup(uuid4().hex, refs if complete else refs[:1])
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before, checkpoint = session.snapshot, session.checkpoint()
    with pytest.raises(ValidationError, match="约束"):
        prepare_collection_rotation(before, refs[:1], draft.frame, (0, 0), 90)
    assert session.snapshot == before and session.checkpoint() == checkpoint
    assert loaded.document.commands == ()
    session.cancel()


@pytest.mark.parametrize("kind", ["coincident", "tangent"])
@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("operation", ["rotate90", "rotate45", "scale", "mirror"])
def test_group_affine_rebinds_inferred_rectangle_references(
    tmp_path: Path, kind: Literal["coincident", "tangent"], complete: bool, operation: str
) -> None:
    from mycad.core.cross_sketch_tangency import tangent_entity_curve
    from mycad.core.drawing_transactions import (
        prepare_collection_mirror,
        prepare_collection_rotation,
        prepare_collection_scale,
    )
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, RectangleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_references import resolve_point_reference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (4, 2))
    if kind == "coincident":
        second = LineEntity(uuid4().hex, (4, 2), (6, 3))
        refs = (
            SketchGeometryReference(rectangle.entity_id, "vertex", 2),
            SketchGeometryReference(second.entity_id, "start"),
        )
    else:
        second = CircleEntity(uuid4().hex, (2, -1), 1)
        refs = (
            SketchGeometryReference(rectangle.entity_id, "segment", 0),
            SketchGeometryReference(second.entity_id, "geometry"),
        )
    relation = SketchConstraint(uuid4().hex, kind, refs, source="inferred")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle, second), (relation,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    objects = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id)
        for item in (rectangle, second)
    )
    group = DrawingGroup(uuid4().hex, objects if complete else objects[:1])
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    if operation.startswith("rotate"):
        angle = 90 if operation == "rotate90" else 45
        command = prepare_collection_rotation(before, objects[:1], draft.frame, (0, 0), angle)
    elif operation == "scale":
        command = prepare_collection_scale(before, objects[:1], draft.frame, (0, 0), 2)
    else:
        command = prepare_collection_mirror(before, objects[:1], draft.frame, (0, 0), (1, 0))
    session.stage(command)
    after = session.snapshot
    updated = after.sketches[-1]
    keep = complete or (kind == "tangent" and operation in ("scale", "mirror"))
    assert len(updated.constraints) == int(keep)
    if keep:
        copied = updated.constraints[0]
        assert copied.constraint_id == relation.constraint_id
        by_id = {item.entity_id: item for item in updated.entities}
        if kind == "coincident":
            first = resolve_point_reference(copied.references[0], by_id)
            last = resolve_point_reference(copied.references[1], by_id)
            assert first is not None and last is not None and first == pytest.approx(last)
        else:
            curves = tuple(
                tangent_entity_curve(by_id[item.entity_id], item.index)
                for item in copied.references
            )
            assert tangent_on_curves(*curves)
    assert after.groups == (group,)
    session.commit()
    path = tmp_path / f"rectangle-{kind}-{complete}-{operation}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


@pytest.mark.parametrize(
    "invalid",
    ["old_version", "forged_matrix", "wrong_vertex", "standalone_matrix", "drop_user_relation"],
)
def test_rectangle_group_affine_rejects_unproven_rebinding_atomically(invalid: str) -> None:
    from copy import deepcopy
    from typing import cast

    from mycad.core.drawing_transactions import prepare_collection_rotation
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (4, 2))
    line = LineEntity(uuid4().hex, (4, 2), (6, 3))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(rectangle.entity_id, "vertex", 2),
            SketchGeometryReference(line.entity_id, "start"),
        ),
        source="inferred",
    )
    unrelated = LineEntity(uuid4().hex, (0, 8), (2, 8))
    confirmed = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(unrelated.entity_id, "geometry"),)
    )
    draft = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (rectangle, line, unrelated) if invalid == "drop_user_relation" else (rectangle, line),
        ()
        if invalid == "standalone_matrix"
        else (relation, confirmed)
        if invalid == "drop_user_relation"
        else (relation,),
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in (rectangle, line)
    )
    group = DrawingGroup(
        uuid4().hex, refs[:1] if invalid in ("old_version", "standalone_matrix") else refs
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before, checkpoint = session.snapshot, session.checkpoint()
    operation = prepare_collection_rotation(before, refs[:1], draft.frame, (0, 0), 45)
    params = deepcopy(operation.params)
    children = cast("list[dict[str, object]]", params["operations"])
    revision = next(item for item in children if item["id"] == "drawing.sketch.revise")
    assert revision["version"] == 81
    payload = cast("dict[str, object]", revision["params"])
    if invalid == "old_version":
        revision["version"] = 79
    elif invalid in ("forged_matrix", "standalone_matrix"):
        proof = cast("list[dict[str, object]]", payload["rectangle_transforms"])[0]
        matrix = cast("list[float]", proof["matrix"])
        matrix[4] += 30
    elif invalid == "drop_user_relation":
        changes = cast("list[dict[str, object]]", payload["revisions"])
        constraints = cast("list[dict[str, object]]", changes[0]["constraints"])
        constraints[:] = [
            item for item in constraints if item["constraint_id"] != confirmed.constraint_id
        ]
    else:
        changes = cast("list[dict[str, object]]", payload["revisions"])
        constraints = cast("list[dict[str, object]]", changes[0]["constraints"])
        references = cast("list[dict[str, object]]", constraints[0]["references"])
        references[0]["index"] = (cast("int", references[0]["index"]) + 1) % 4
    with pytest.raises(ValidationError):
        session.stage(ReplayAppend(operation.command_id, operation.version, params, "local"))
    assert session.snapshot == before and session.checkpoint() == checkpoint
    assert not loaded.document.commands
    session.cancel()


def test_unconstrained_group_rectangle_rotates_and_replays_with_proven_identity(
    tmp_path: Path,
) -> None:
    from mycad.core.drawing_transactions import prepare_collection_rotation
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (4, 2))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", rectangle.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(prepare_collection_rotation(before, (ref,), draft.frame, (0, 0), 45))
    after = session.snapshot
    transformed = after.sketches[-1].entities[0]
    assert isinstance(transformed, PolylineEntity) and transformed.entity_id == rectangle.entity_id
    assert after.groups == (group,)
    session.commit()
    exchange = tmp_path / "rotated-rectangle.dxf"
    write_sketches_dxf(after.sketches, exchange, drawing_layers=after.layers, groups=after.groups)
    imported = read_sketch_dxf(exchange)
    assert imported.sketch is not None and len(imported.groups) == 1
    imported_entity = imported.sketch.entities[0]
    assert isinstance(imported_entity, PolylineEntity)
    assert imported.groups[0].members[0].object_id == imported_entity.entity_id
    later = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (LineEntity(uuid4().hex, (8, 0), (9, 2)),),
    )
    app.commit_new_sketch(services, loaded, later, session_identity=1)
    path = tmp_path / "rectangle-no-relations.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.redo_operation()
    assert services.kernel.sketches[-1] == later


def test_rectangle_group_transform_preserves_unrelated_confirmed_constraints(
    tmp_path: Path,
) -> None:
    from mycad.core.drawing_transactions import prepare_collection_rotation
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, RectangleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (4, 2))
    joined = LineEntity(uuid4().hex, (4, 2), (6, 3))
    separate = LineEntity(uuid4().hex, (0, 8), (2, 8))
    tangent_line = LineEntity(uuid4().hex, (-2, 11), (2, 11))
    circle = CircleEntity(uuid4().hex, (0, 12), 1)
    coincident = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(rectangle.entity_id, "vertex", 2),
            SketchGeometryReference(joined.entity_id, "start"),
        ),
        source="inferred",
    )
    horizontal = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(separate.entity_id, "geometry"),)
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(separate.entity_id, "geometry"),),
        2,
        "mm",
        driving=False,
        position_mm=(1, 10),
    )
    tangent = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(tangent_line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    draft = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (rectangle, joined, separate, tangent_line, circle),
        (coincident, horizontal, dimension, tangent),
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id)
        for item in (rectangle, joined)
    )
    group = DrawingGroup(uuid4().hex, refs)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(prepare_collection_rotation(before, refs[:1], draft.frame, (0, 0), 45))
    after = session.snapshot
    assert after.sketches[-1].entities[-3:] == (separate, tangent_line, circle)
    assert after.sketches[-1].constraints[1:] == (horizontal, dimension, tangent)
    session.commit()
    path = tmp_path / "rectangle-unrelated.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_rectangle_group_transform_rebinds_cross_tangent_and_drops_local_inference(
    tmp_path: Path,
) -> None:
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.drawing_transactions import prepare_collection_rotation
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, RectangleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, -20))
    line = LineEntity(uuid4().hex, (20, 0), (25, 2))
    circle = CircleEntity(uuid4().hex, (5, -5), 5)
    inferred = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(rectangle.entity_id, "vertex", 1),
            SketchGeometryReference(line.entity_id, "start"),
        ),
        source="inferred",
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle, line), (inferred,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    pairs = tuple(
        (
            SketchGeometryReference(rectangle.entity_id, "segment", index),
            SketchGeometryReference(circle.entity_id, "geometry"),
        )
        for index in (0, 3)
    )
    relations = app.draft_cross_relations((first,), second, pairs)
    for relation in relations:
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    refs = (
        DrawingObjectRef("geometry", rectangle.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
    )
    group = DrawingGroup(uuid4().hex, refs)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(prepare_collection_rotation(before, refs[:1], draft.frame, (0, 0), 45))
    after = session.snapshot
    updated = next(item for item in after.sketches if item.sketch_id == first.sketch_id)
    assert updated.entities[1] == line and not updated.constraints
    assert {item.relation_id for item in after.cross_tangencies} == {
        item.relation_id for item in relations
    }
    validate_tangency_component(after.sketches, after.cross_tangencies, first.sketch_id)
    persisted_before = replace(
        before, sketches=tuple(s for s in before.sketches if s.sketch_id != draft.sketch_id)
    )
    persisted_after = replace(
        after, sketches=tuple(s for s in after.sketches if s.sketch_id != draft.sketch_id)
    )
    session.commit()
    path = tmp_path / "rectangle-cross-local.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == persisted_before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == persisted_after


@pytest.mark.parametrize("size", [1e-8, 1e-6])
def test_small_group_rectangle_can_rotate_with_unique_proven_edges(
    tmp_path: Path, size: float
) -> None:
    from mycad.core.drawing_transactions import prepare_collection_rotation
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (size, 1e-3))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", rectangle.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(prepare_collection_rotation(before, (ref,), draft.frame, (0, 0), 45))
    after = session.snapshot
    rotated = after.sketches[-1].entities[0]
    assert isinstance(rotated, PolylineEntity) and rotated.entity_id == rectangle.entity_id
    assert after.groups == (group,)
    session.commit()
    path = tmp_path / f"small-rectangle-{size}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_thin_rectangle_group_rotation_rebinds_local_inference(tmp_path: Path) -> None:
    from mycad.core.drawing_transactions import prepare_collection_rotation
    from mycad.core.persistence import save_document
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_references import resolve_point_reference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (1e-8, 1e-3))
    line = LineEntity(uuid4().hex, (1e-8, 1e-3), (0.1, 0.2))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(rectangle.entity_id, "vertex", 2),
            SketchGeometryReference(line.entity_id, "start"),
        ),
        source="inferred",
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle, line), (relation,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in (rectangle, line)
    )
    group = DrawingGroup(uuid4().hex, refs)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(prepare_collection_rotation(before, refs[:1], draft.frame, (0, 0), 45))
    after = session.snapshot
    sketch = after.sketches[-1]
    assert (
        len(sketch.constraints) == 1
        and sketch.constraints[0].constraint_id == relation.constraint_id
    )
    entities = {item.entity_id: item for item in sketch.entities}
    first, second = (
        resolve_point_reference(item, entities) for item in sketch.constraints[0].references
    )
    assert first is not None and second is not None and first == pytest.approx(second)
    session.commit()
    path = tmp_path / "thin-rectangle-inferred.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_thin_rectangle_group_rotation_rebinds_cross_sketch_tangency(tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.drawing_transactions import prepare_collection_rotation
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, RectangleEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (1e-8, 1e-3))
    circle = CircleEntity(uuid4().hex, (1e-4 + 1e-8, 5e-4), 1e-4)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relations = app.draft_cross_relations(
        (first,),
        second,
        (
            (
                SketchGeometryReference(rectangle.entity_id, "segment", 1),
                SketchGeometryReference(circle.entity_id, "geometry"),
            ),
        ),
    )
    assert len(relations) == 1
    app.commit_cross_sketch_tangency(services, loaded, relations[0], session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    refs = (
        DrawingObjectRef("geometry", rectangle.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
    )
    group = DrawingGroup(uuid4().hex, refs)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(prepare_collection_rotation(before, refs[:1], draft.frame, (0, 0), 45))
    after = session.snapshot
    assert len(after.cross_tangencies) == 1
    assert after.cross_tangencies[0].relation_id == relations[0].relation_id
    validate_tangency_component(after.sketches, after.cross_tangencies, first.sketch_id)
    persisted_before = replace(
        before, sketches=tuple(s for s in before.sketches if s.sketch_id != draft.sketch_id)
    )
    persisted_after = replace(
        after, sketches=tuple(s for s in after.sketches if s.sketch_id != draft.sketch_id)
    )
    session.commit()
    path = tmp_path / "thin-rectangle-cross-tangent.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == persisted_before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == persisted_after


def test_group_rotates_far_from_origin_rectangle_and_reopens(tmp_path: Path) -> None:
    from mycad.core.drawing_transactions import prepare_collection_rotation
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (1e9, 1e9), (1e9 + 1, 1e9 + 2))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", rectangle.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    session.stage(prepare_collection_rotation(before, (ref,), draft.frame, (0, 0), 30))
    after = session.snapshot
    transformed = after.sketches[-1].entities[0]
    assert isinstance(transformed, PolylineEntity) and transformed.entity_id == rectangle.entity_id
    assert after.groups == (group,)
    session.stage(prepare_collection_rotation(after, (ref,), draft.frame, (0, 0), 15))
    rotated_again = session.snapshot
    assert rotated_again.groups == (group,)
    assert rotated_again.sketches[-1].entities[0].entity_id == rectangle.entity_id
    session.commit()
    path = tmp_path / "far-rectangle.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == rotated_again


def test_legacy_far_coordinate_polygon_file_remains_readable(tmp_path: Path) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    polygon = PolylineEntity(
        uuid4().hex,
        (
            (100000331, 100000970),
            (100000336, 100000983),
            (100000341, 100000996),
        ),
        closed=True,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polygon,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    path = tmp_path / "legacy-far-polygon.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == (sketch,)
    reopened.bus.undo_operation()
    assert not services.kernel.sketches
    reopened.bus.redo_operation()
    assert services.kernel.sketches == (sketch,)
