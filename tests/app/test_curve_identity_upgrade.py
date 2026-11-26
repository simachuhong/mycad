# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Versioned legacy curve identity upgrade stays atomic and replayable."""

from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.exceptions import ValidationError
from mycad.core.geometric_tolerance_topology import prepare_curve_identity_upgrade
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, SplineEntity, WorkPlaneFrame


def test_import_reordered_curve_ids_replays_and_rejects_collision(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance_topology import new_curve_point_identities

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    identity = uuid4().hex
    ids = new_curve_point_identities(identity, "polyline", 3)
    curve = PolylineEntity(identity, ((2, 1), (1, 0), (0, 0)), point_ids=tuple(reversed(ids)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, imported_curve_ids=True)
    assert services.kernel.sketches == (sketch,)
    loaded.bus.undo()
    loaded.bus.redo()
    path = tmp_path / "import.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=())
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == (sketch,)
    duplicate = replace(sketch, sketch_id=uuid4().hex)
    with pytest.raises(ValidationError, match="身份"):
        app.commit_new_sketch(
            restored, reopened, duplicate, session_identity=0, imported_curve_ids=True
        )
    forged_curve = replace(curve, entity_id=uuid4().hex)
    forged = replace(sketch, sketch_id=uuid4().hex, entities=(forged_curve,))
    with pytest.raises(ValidationError, match="身份"):
        app.commit_new_sketch(
            restored, reopened, forged, session_identity=0, imported_curve_ids=True
        )


def test_curve_identity_upgrade_replays_undoes_and_reopens(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    spline = SplineEntity(uuid4().hex, ((0, 0), (1, 0), (2, 1), (3, 1)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline, spline))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    records = prepare_curve_identity_upgrade(sketch, (polyline.entity_id, spline.entity_id))
    params = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
        "records": [record.to_mapping() for record in records],
    }
    loaded.bus.execute("drawing.curve_identity.upgrade", params, "local")
    upgraded = services.kernel.sketches[0]
    assert upgraded.entities == (
        replace(polyline, point_ids=records[0].point_ids),
        replace(spline, point_ids=records[1].point_ids),
    )
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)
    loaded.bus.redo()
    assert services.kernel.sketches == (upgraded,)
    path = tmp_path / "identities.my2d"
    save_document(loaded.document, path)
    restored_services = app.build_app(discoverers=())
    app.open_app_document(restored_services, path)
    assert restored_services.kernel.sketches == (upgraded,)


def test_selected_curve_identity_upgrade_is_one_undoable_operation(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    spline = SplineEntity(uuid4().hex, ((0, 0), (1, 0), (2, 1), (3, 1)))
    sketches = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)) for entity in (polyline, spline)
    )
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (12, 4),
        (10, 0),
        attachment=DatumAttachment(
            sketches[0].sketch_id, SketchGeometryReference(polyline.entity_id, "vertex", 1)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    app.upgrade_selected_curve_identities(
        services, loaded, (polyline.entity_id, spline.entity_id), session_identity=0
    )
    upgraded = services.kernel.sketches
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert all(
        isinstance(item.entities[0], PolylineEntity | SplineEntity) and item.entities[0].point_ids
        for item in upgraded
    )
    assert tuple(item.entities[0].entity_id for item in upgraded) == (
        polyline.entity_id,
        spline.entity_id,
    )
    loaded.bus.undo_operation()
    assert services.kernel.sketches == sketches
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.sketches == upgraded
    path = tmp_path / "upgraded.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=())
    app.open_app_document(restored, path)
    assert restored.kernel.sketches == upgraded
    assert restored.kernel.drawing_datum_identifiers == (datum,)


def test_selected_curve_identity_upgrade_rejects_mixed_objects_without_changes() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    line = LineEntity(uuid4().hex, (0, 0), (1, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve, line))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="多段线或样条"):
        app.upgrade_selected_curve_identities(
            services, loaded, (curve.entity_id, line.entity_id), session_identity=0
        )
    assert services.kernel.sketches == (sketch,)
    assert loaded.document.command_count == count


def test_selected_curve_identity_upgrade_skips_existing_identities() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    second = PolylineEntity(uuid4().hex, ((1, 1), (2, 1), (2, 2)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    app.upgrade_selected_curve_identities(services, loaded, (first.entity_id,), session_identity=0)
    current = services.kernel.sketches[0]
    app.upgrade_selected_curve_identities(
        services, loaded, (first.entity_id, second.entity_id), session_identity=0
    )
    upgraded = services.kernel.sketches[0]
    assert upgraded.entities[0] == current.entities[0]
    assert isinstance(upgraded.entities[1], PolylineEntity) and upgraded.entities[1].point_ids
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="已有点身份"):
        app.upgrade_selected_curve_identities(
            services, loaded, (first.entity_id, second.entity_id), session_identity=0
        )
    assert services.kernel.sketches == (upgraded,)
    assert loaded.document.command_count == count


def test_selected_curve_identity_upgrade_migrates_legacy_archive(tmp_path: Path) -> None:
    from mycad.core.bus import CommandBus
    from mycad.core.document import Document
    from mycad.core.persistence import LoadedDocument

    services = app.build_app(discoverers=())
    document = Document(
        services.registry, archive_version=4, document_type="drawing2d", document_kind="sketch"
    )
    loaded = LoadedDocument(
        document,
        CommandBus(document, services.registry, services.kernel, app.handlers_for(services)),
    )
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    assert document.archive_version == 4
    app.upgrade_selected_curve_identities(services, loaded, (curve.entity_id,), session_identity=0)
    assert document.archive_version >= 6
    path = tmp_path / "legacy-upgraded.my2d"
    save_document(document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches == services.kernel.sketches


def test_selected_curve_identity_upgrade_rolls_back_if_any_layer_is_locked() -> None:
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    layers = services.kernel.drawing_layers.add(SketchLayer("锁层"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    first = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    second = PolylineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5)), layer_name="锁层")
    for curve in (first, second):
        sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,), layers=layers)
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "锁层" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    before = services.kernel.sketches
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="锁定"):
        app.upgrade_selected_curve_identities(
            services, loaded, (first.entity_id, second.entity_id), session_identity=0
        )
    assert services.kernel.sketches == before
    assert loaded.document.command_count == count


@pytest.mark.parametrize("problem", ["stale", "forged", "duplicate"])
def test_curve_identity_upgrade_rejects_invalid_records_without_partial_change(
    problem: str,
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    entity = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    record = prepare_curve_identity_upgrade(sketch, (entity.entity_id,))[0]
    if problem == "forged":
        record = replace(record, point_ids=(uuid4().hex, *record.point_ids[1:]))
    records = [record.to_mapping()] * (2 if problem == "duplicate" else 1)
    params = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": "0" * 64 if problem == "stale" else sketch.local_state_digest(),
        "records": records,
    }
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.curve_identity.upgrade", params, "local")
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,)


def test_curve_identity_upgrade_survives_unrelated_array_consumer_rebuild(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    curve = PolylineEntity(uuid4().hex, ((0, 0), (1, 0), (1, 1)))
    source = LineEntity(uuid4().hex, (0, 5), (2, 5))
    target = LineEntity(uuid4().hex, (5, 5), (7, 5))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve, source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    member = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, member, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    record = prepare_curve_identity_upgrade(sketch, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    loaded.bus.execute(
        "drawing.array.update",
        {"array_id": array.array_id, "row_spacing": 0, "column_spacing": 8},
        "local",
    )
    assert services.kernel.sketches[0].entities[0] == replace(curve, point_ids=record.point_ids)
    path = tmp_path / "rebuild.my2d"
    save_document(loaded.document, path)
    restored_services = app.build_app(discoverers=())
    app.open_app_document(restored_services, path)
    assert restored_services.kernel.sketches == services.kernel.sketches


def test_curve_identity_upgrade_rejects_locked_layer() -> None:
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    layers = services.kernel.drawing_layers.add(SketchLayer("曲线"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    curve = PolylineEntity(uuid4().hex, ((0, 0), (1, 0), (1, 1)), layer_name="曲线")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,), layers=layers)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "曲线" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    current = services.kernel.sketches[0]
    record = prepare_curve_identity_upgrade(current, (curve.entity_id,))[0]
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="锁定"):
        loaded.bus.execute(
            "drawing.curve_identity.upgrade",
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "records": [record.to_mapping()],
            },
            "local",
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (current,)


def test_curve_identity_upgrade_preserves_attached_datum() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(curve.entity_id, "vertex", 1)
    )
    datum = DatumIdentifier(uuid4().hex, "A", (12, 4), (10, 0), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    original_datum = services.kernel.drawing_datum_identifiers
    record = prepare_curve_identity_upgrade(sketch, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    assert services.kernel.drawing_datum_identifiers == original_datum
    loaded.bus.undo()
    assert services.kernel.drawing_datum_identifiers == original_datum
    loaded.bus.redo()
    assert services.kernel.drawing_datum_identifiers == original_datum


def test_identity_aware_revision_preserves_ids_and_replays(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    record = prepare_curve_identity_upgrade(sketch, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    current = services.kernel.sketches[0]
    updated_curve = replace(
        curve, points_mm=((0, 0), (10, 0), (11, 12)), point_ids=record.point_ids
    )
    updated = replace(current, entities=(updated_curve,))
    state = updated.to_state_mapping()
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ]
    }
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=64)
    assert services.kernel.sketches == (updated,)
    loaded.bus.undo()
    assert services.kernel.sketches == (current,)
    loaded.bus.redo()
    path = tmp_path / "edited.my2d"
    save_document(loaded.document, path)
    restored_services = app.build_app(discoverers=())
    app.open_app_document(restored_services, path)
    assert restored_services.kernel.sketches == (updated,)


@pytest.mark.parametrize("problem", ["dropped", "reordered"])
def test_identity_aware_revision_rejects_identity_changes(problem: str) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    record = prepare_curve_identity_upgrade(sketch, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    current = services.kernel.sketches[0]
    bad_ids = () if problem == "dropped" else tuple(reversed(record.point_ids))
    changed = replace(current, entities=(replace(curve, point_ids=bad_ids),)).to_state_mapping()
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="身份"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": current.sketch_id,
                        "base_state_sha256": current.local_state_digest(),
                        "entities": changed["entities"],
                        "constraints": changed["constraints"],
                    }
                ]
            },
            "local",
            version=64,
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (current,)


def test_identity_aware_revision_can_copy_curve_and_reopen(tmp_path: Path) -> None:
    from mycad.core.sketch_edit import copy_entities

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    record = prepare_curve_identity_upgrade(sketch, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    current = services.kernel.sketches[0]
    copied = copy_entities(current.entities, (curve.entity_id,), (20, 0))
    updated = replace(current, entities=copied)
    state = updated.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": current.sketch_id,
                    "base_state_sha256": current.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=64,
    )
    assert services.kernel.sketches == (updated,)
    loaded.bus.undo()
    assert services.kernel.sketches == (current,)
    loaded.bus.redo()
    path = tmp_path / "copy.my2d"
    save_document(loaded.document, path)
    restored_services = app.build_app(discoverers=())
    app.open_app_document(restored_services, path)
    assert restored_services.kernel.sketches == (updated,)


def test_identity_aware_array_spacing_preserves_member_ids_and_replays(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = PolylineEntity(uuid4().hex, ((0, 0), (1, 0), (1, 1)))
    target = PolylineEntity(uuid4().hex, ((5, 0), (6, 0), (6, 1)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    member = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, member, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    records = prepare_curve_identity_upgrade(sketch, (source.entity_id, target.entity_id))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    current = services.kernel.sketches[0]
    loaded.bus.execute(
        "drawing.array.update",
        {"array_id": array.array_id, "row_spacing": 0, "column_spacing": 8},
        "local",
    )
    updated = services.kernel.sketches[0]
    moved = updated.entities[1]
    assert isinstance(moved, PolylineEntity)
    assert moved.points_mm == ((8, 0), (9, 0), (9, 1))
    assert moved.point_ids == records[1].point_ids
    loaded.bus.undo()
    assert services.kernel.sketches == (current,)
    loaded.bus.redo()
    path = tmp_path / "array-identities.my2d"
    save_document(loaded.document, path)
    restored_services = app.build_app(discoverers=())
    app.open_app_document(restored_services, path)
    assert restored_services.kernel.sketches == (updated,)


def test_identity_aware_sketch_creation_preserves_copied_curve_and_datum(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_topology import new_curve_point_identities
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    identity = uuid4().hex
    curve = PolylineEntity(
        identity,
        ((20, 0), (30, 0), (30, 10)),
        point_ids=new_curve_point_identities(identity, "polyline", 3),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (32, 4),
        (30, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(identity, "vertex", 1)
        ),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, imported_datums=(datum,))
    assert any(
        command.id == "sketch.create" and command.version == 57
        for command in loaded.document.commands
    )
    created = services.kernel.sketches[0]
    assert created.entities == (curve,)
    assert services.kernel.drawing_datum_identifiers[0].attachment == datum.attachment
    path = tmp_path / "created.my2d"
    save_document(loaded.document, path)
    restored_services = app.build_app(discoverers=())
    app.open_app_document(restored_services, path)
    assert restored_services.kernel.sketches == (created,)
    assert restored_services.kernel.drawing_datum_identifiers[0].attachment == datum.attachment


def test_identity_aware_sketch_creation_rejects_forged_point_ids() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    curve = PolylineEntity(
        uuid4().hex, ((0, 0), (1, 0), (1, 1)), point_ids=tuple(uuid4().hex for _ in range(3))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="身份"):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    assert loaded.document.command_count == count
    assert not services.kernel.sketches


@pytest.mark.parametrize("kind", ["polyline", "spline"])
def test_identity_aware_constraint_replays_and_old_version_rejects(
    tmp_path: Path, kind: str
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    points = ((20, 0), (22, 0), (22, 2), (24, 2))
    curve = (
        PolylineEntity(uuid4().hex, points)
        if kind == "polyline"
        else SplineEntity(uuid4().hex, points)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, curve))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    record = prepare_curve_identity_upgrade(sketch, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    current = services.kernel.sketches[0]
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=20,
        unit="mm",
    )
    result = services.kernel.preview_sketch_constraint(current, constraint)
    if result.status == "unavailable":
        pytest.skip(result.message or "PlaneGCS is unavailable")
    assert result.status == "success", result.message
    params = result.command_params(current, constraint, local_frame=True)
    with pytest.raises(ValidationError, match="版本"):
        loaded.bus.execute("sketch.constraint.add", params, "local", version=10)
    loaded.bus.execute("sketch.constraint.add", params, "local", version=11)
    updated = services.kernel.sketches[0]
    solved = updated.entities[1]
    assert (
        isinstance(solved, PolylineEntity | SplineEntity) and solved.point_ids == record.point_ids
    )
    loaded.bus.undo()
    assert services.kernel.sketches == (current,)
    loaded.bus.redo()
    changed_constraint = replace(constraint, value=25)
    update_result = services.kernel.preview_sketch_constraint_update(updated, changed_constraint)
    assert update_result.status == "success", update_result.message
    update_params = update_result.command_params(updated, changed_constraint, local_frame=True)
    with pytest.raises(ValidationError, match="版本"):
        loaded.bus.execute("sketch.constraint.update", update_params, "local", version=8)
    loaded.bus.execute("sketch.constraint.update", update_params, "local", version=9)
    final = services.kernel.sketches[0]
    solved = final.entities[1]
    assert (
        isinstance(solved, PolylineEntity | SplineEntity) and solved.point_ids == record.point_ids
    )
    loaded.bus.undo()
    assert services.kernel.sketches == (updated,)
    loaded.bus.redo()
    path = tmp_path / f"constraint-{kind}.my2d"
    save_document(loaded.document, path)
    restored_services = app.build_app(discoverers=())
    app.open_app_document(restored_services, path)
    assert restored_services.kernel.sketches == (final,)


@pytest.mark.parametrize("legacy_archive", [False, True])
def test_cross_sketch_dimension_preserves_curve_ids_and_datum(
    tmp_path: Path, legacy_archive: bool
) -> None:
    from mycad.core.bus import CommandBus
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.document import Document
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.persistence import LoadedDocument
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    if legacy_archive:
        document = Document(
            services.registry, archive_version=6, document_type="drawing2d", document_kind="sketch"
        )
        loaded = LoadedDocument(
            document=document,
            bus=CommandBus(
                document, services.registry, services.kernel, app.handlers_for(services)
            ),
        )
    else:
        loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    curve = PolylineEntity(uuid4().hex, ((20, 0), (22, 0), (22, 2)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, curve))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    current = next(item for item in services.kernel.sketches if item.sketch_id == first.sketch_id)
    record = prepare_curve_identity_upgrade(current, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (25, 5),
        (22, 0),
        attachment=DatumAttachment(
            first.sketch_id, SketchGeometryReference(curve.entity_id, "vertex", 1)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    if legacy_archive:
        assert loaded.document.archive_version == 6
    before, datum_before = services.kernel.sketches, services.kernel.drawing_datum_identifiers
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 12, "mm"
    )
    app.commit_cross_sketch_dimension(
        services, loaded, first.sketch_id, dimension, session_identity=0
    )
    assert loaded.document.commands[-1].version == 64
    assert loaded.document.archive_version == 8
    after = services.kernel.sketches
    solved = next(item for item in after if item.sketch_id == first.sketch_id).entities[1]
    assert isinstance(solved, PolylineEntity) and solved.point_ids == record.point_ids
    assert services.kernel.drawing_datum_identifiers == datum_before
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    path = tmp_path / "cross-identity.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=())
    app.open_app_document(restored, path)
    assert restored.kernel.sketches == after
    assert restored.kernel.drawing_datum_identifiers == datum_before


def test_linked_dimension_on_identity_polyline_segment_preserves_datum(tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, curve.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    current = next(item for item in services.kernel.sketches if item.sketch_id == first.sketch_id)
    record = prepare_curve_identity_upgrade(current, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    attachment = DatumAttachment(
        first.sketch_id, SketchGeometryReference(curve.entity_id, "segment", 0), 0.25, 2
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 6), (2.5, 0), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    before = services.kernel.sketches
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 3, "mm"
    )
    app.commit_cross_sketch_dimension(
        services, loaded, second.sketch_id, dimension, session_identity=0
    )
    assert loaded.document.commands[-1].version == 64
    after = services.kernel.sketches
    changed = next(item for item in after if item.sketch_id == first.sketch_id)
    solved = changed.entities[0]
    assert isinstance(solved, PolylineEntity) and solved.point_ids == record.point_ids
    assert solved.points_mm != curve.points_mm
    attached = services.kernel.drawing_datum_identifiers[0]
    expected = resolve_attachment_local(attachment, {solved.entity_id: solved})
    assert expected is not None and attached.target_mm == pytest.approx(expected)
    assert attached.target_mm != pytest.approx(datum.target_mm)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    path = tmp_path / "segment-identity.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=())
    app.open_app_document(restored, path)
    assert restored.kernel.sketches == after
    assert restored.kernel.drawing_datum_identifiers == (attached,)


def test_exact_polyline_reorder_preserves_point_identity_and_datum(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    record = prepare_curve_identity_upgrade(sketch, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    current = services.kernel.sketches[0]
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(curve.entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    original_datum = services.kernel.drawing_datum_identifiers
    updated_curve = replace(
        curve,
        points_mm=tuple(reversed(curve.points_mm)),
        point_ids=tuple(reversed(record.point_ids)),
    )
    updated = replace(current, entities=(updated_curve,))
    state = updated.to_state_mapping()
    mapping = PolylineTopologyMap(curve.entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    wrong = replace(updated_curve, point_ids=record.point_ids)
    wrong_state = replace(current, entities=(wrong,)).to_state_mapping()
    bad_params = {
        **params,
        "revisions": [{**params["revisions"][0], "entities": wrong_state["entities"]}],
    }
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="身份"):
        loaded.bus.execute("drawing.sketch.revise", bad_params, "local", version=64)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (current,)
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise", {"revisions": params["revisions"]}, "local", version=64
        )
    assert loaded.document.command_count == count
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=64)
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.attachment is not None and moved.attachment.reference.index == 2
    assert moved.target_mm == pytest.approx((0, 0))
    assert services.kernel.sketches == (updated,)
    loaded.bus.undo()
    assert services.kernel.sketches == (current,)
    assert services.kernel.drawing_datum_identifiers == original_datum
    loaded.bus.redo()
    path = tmp_path / "identity-reorder.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=())
    app.open_app_document(restored, path)
    assert restored.kernel.sketches == (updated,)
    assert restored.kernel.drawing_datum_identifiers == (moved,)


def test_array_replacement_stays_stable_after_identity_source_reorder(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    replacement = replace(
        source, entity_id=uuid4().hex, points_mm=tuple((x + 30, y) for x, y in source.points_mm)
    )
    target = replace(
        source, entity_id=uuid4().hex, points_mm=tuple((x, y + 20) for x, y in source.points_mm)
    )
    sketches = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,)) for item in (source, replacement, target)
    )
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(
        ArrayEntityRef(sketch.sketch_id, sketch.entities[0].entity_id) for sketch in sketches
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketches[0].frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    for sketch in sketches:
        current = next(
            item for item in services.kernel.sketches if item.sketch_id == sketch.sketch_id
        )
        records = prepare_curve_identity_upgrade(current, (sketch.entities[0].entity_id,))
        loaded.bus.execute(
            "drawing.curve_identity.upgrade",
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "records": [record.to_mapping() for record in records],
            },
            "local",
        )
    target_before = next(
        item for item in services.kernel.sketches if item.sketch_id == sketches[2].sketch_id
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (8, 25),
        (2.5, 20),
        attachment=DatumAttachment(
            sketches[2].sketch_id, SketchGeometryReference(target.entity_id, "segment", 0), 0.25, 4
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    original_datum = services.kernel.drawing_datum_identifiers
    current = next(
        item for item in services.kernel.sketches if item.sketch_id == sketches[0].sketch_id
    )
    original = current.entities[0]
    assert isinstance(original, PolylineEntity)
    order = (0, 3, 2, 1)
    changed = replace(
        original,
        points_mm=tuple(original.points_mm[i] for i in order),
        point_ids=tuple(original.point_ids[i] for i in order),
    )
    state = replace(current, entities=(changed,)).to_state_mapping()
    mapping = PolylineTopologyMap(original.entity_id, order, 4, True)
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": current.sketch_id,
                    "base_state_sha256": current.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ],
            "polyline_topology_maps": [
                {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
            ],
        },
        "local",
        version=64,
    )
    assert (
        next(item for item in services.kernel.sketches if item.sketch_id == sketches[2].sketch_id)
        == target_before
    )
    assert services.kernel.drawing_datum_identifiers == original_datum
    after = services.kernel.sketches
    loaded.bus.undo()
    loaded.bus.redo()
    path = tmp_path / "replacement-identities.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=())
    app.open_app_document(restored, path)
    assert restored.kernel.sketches == after
    assert restored.kernel.drawing_datum_identifiers == original_datum


def test_replacement_source_reorder_remaps_member_identity_and_datum(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    replacement = replace(
        source, entity_id=uuid4().hex, points_mm=tuple((x + 30, y) for x, y in source.points_mm)
    )
    target = replace(
        source, entity_id=uuid4().hex, points_mm=tuple((x, y + 20) for x, y in source.points_mm)
    )
    sketches = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,)) for item in (source, replacement, target)
    )
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(
        ArrayEntityRef(sketch.sketch_id, sketch.entities[0].entity_id) for sketch in sketches
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketches[0].frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    for sketch in sketches:
        current = next(
            item for item in services.kernel.sketches if item.sketch_id == sketch.sketch_id
        )
        records = prepare_curve_identity_upgrade(current, (sketch.entities[0].entity_id,))
        loaded.bus.execute(
            "drawing.curve_identity.upgrade",
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "records": [record.to_mapping() for record in records],
            },
            "local",
        )
    before = services.kernel.sketches
    target_before = next(
        item for item in before if item.sketch_id == sketches[2].sketch_id
    ).entities[0]
    assert isinstance(target_before, PolylineEntity)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (8, 25),
        (2.5, 20),
        attachment=DatumAttachment(
            sketches[2].sketch_id, SketchGeometryReference(target.entity_id, "segment", 0), 0.25, 4
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = next(
        item for item in services.kernel.sketches if item.sketch_id == sketches[1].sketch_id
    )
    original = current.entities[0]
    assert isinstance(original, PolylineEntity)
    order = (0, 3, 2, 1)
    changed = replace(
        original,
        points_mm=tuple(original.points_mm[i] for i in order),
        point_ids=tuple(original.point_ids[i] for i in order),
    )
    state = replace(current, entities=(changed,)).to_state_mapping()
    mapping = PolylineTopologyMap(original.entity_id, order, 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=64)
    shifted_order = (1, 2, 3, 0)
    shifted = replace(
        original,
        points_mm=tuple(original.points_mm[i] for i in shifted_order),
        point_ids=tuple(original.point_ids[i] for i in shifted_order),
    )
    shifted_state = replace(current, entities=(shifted,)).to_state_mapping()
    shifted_map = PolylineTopologyMap(original.entity_id, (3, 0, 1, 2), 4, True)
    shifted_params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": shifted_state["entities"],
                "constraints": shifted_state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": shifted_map.to_mapping()}
        ],
    }
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", shifted_params, "local", version=65)
    assert loaded.document.command_count == count and services.kernel.sketches == before
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=65)
    after = services.kernel.sketches
    member = next(item for item in after if item.sketch_id == sketches[2].sketch_id).entities[0]
    assert isinstance(member, PolylineEntity)
    assert member.point_ids == tuple(target_before.point_ids[i] for i in order)
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.attachment is not None and moved.attachment.reference.index == 3
    assert moved.target_mm == pytest.approx((2.5, 20))
    loaded.bus.undo()
    assert services.kernel.sketches == before
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo()
    path = tmp_path / "replacement-source-reorder.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=())
    app.open_app_document(restored, path)
    assert restored.kernel.sketches == after
    assert restored.kernel.drawing_datum_identifiers == (moved,)


def test_exact_array_reorder_preserves_member_point_ids_and_annotations(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import (
        DatumAttachment,
        DatumIdentifier,
        FeatureControlFrame,
        ToleranceRow,
    )
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    target = PolylineEntity(uuid4().hex, ((0, 20), (10, 20), (10, 30)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 1, 0),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    records = prepare_curve_identity_upgrade(sketch, (source.entity_id, target.entity_id))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    current = services.kernel.sketches[0]
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 24),
        (0, 20),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(target.entity_id, "vertex", 0)
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (4, 25),
        leader_target_mm=(2.5, 20),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(target.entity_id, "segment", 0), 0.25, 2
        ),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    before_annotations = (
        services.kernel.drawing_datum_identifiers,
        services.kernel.drawing_tolerance_frames,
    )
    reversed_source = replace(
        source,
        points_mm=tuple(reversed(source.points_mm)),
        point_ids=tuple(reversed(records[0].point_ids)),
    )
    frozen = replace(current, entities=(reversed_source, current.entities[1])).to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": frozen["entities"],
                "constraints": frozen["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    wrong_source = replace(reversed_source, point_ids=records[0].point_ids)
    wrong_state = replace(current, entities=(wrong_source, current.entities[1])).to_state_mapping()
    bad_params = {
        **params,
        "revisions": [{**params["revisions"][0], "entities": wrong_state["entities"]}],
    }
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="身份"):
        loaded.bus.execute("drawing.sketch.revise", bad_params, "local", version=64)
    assert loaded.document.command_count == count and services.kernel.sketches == (current,)
    assert (
        services.kernel.drawing_datum_identifiers,
        services.kernel.drawing_tolerance_frames,
    ) == before_annotations
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=64)
    after = services.kernel.sketches[0]
    member = after.entities[1]
    assert isinstance(member, PolylineEntity)
    assert member.points_mm == tuple(reversed(target.points_mm))
    assert member.point_ids == tuple(reversed(records[1].point_ids))
    moved_datum = services.kernel.drawing_datum_identifiers[0]
    moved_frame = services.kernel.drawing_tolerance_frames[0]
    assert moved_datum.attachment is not None and moved_datum.attachment.reference.index == 2
    assert (
        moved_frame.leader_attachment is not None
        and moved_frame.leader_attachment.reference.index == 1
    )
    assert moved_frame.leader_attachment.parameter == pytest.approx(0.75)
    assert moved_datum.target_mm == pytest.approx((0, 20))
    assert moved_frame.leader_target_mm == pytest.approx((2.5, 20))
    loaded.bus.undo()
    assert services.kernel.sketches == (current,)
    assert (
        services.kernel.drawing_datum_identifiers,
        services.kernel.drawing_tolerance_frames,
    ) == before_annotations
    loaded.bus.redo()
    path = tmp_path / "array-reordered-identities.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=())
    app.open_app_document(restored, path)
    assert restored.kernel.sketches == (after,)
    assert restored.kernel.drawing_datum_identifiers == (moved_datum,)
    assert restored.kernel.drawing_tolerance_frames == (moved_frame,)


def test_rotated_cross_sketch_array_reorder_preserves_member_identity() -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    rotated = rotate_entities((source,), (source.entity_id,), (0, 0), 90)[0]
    translated = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
    assert isinstance(translated, PolylineEntity)
    target = replace(translated, entity_id=uuid4().hex)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source_ref, target_ref = (
        ArrayEntityRef(first.sketch_id, source.entity_id),
        ArrayEntityRef(second.sketch_id, target.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex,
        first.frame,
        2,
        1,
        20,
        0,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 1, 0, rotation_deg=90),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    for sketch, entity in ((first, source), (second, target)):
        current = next(
            item for item in services.kernel.sketches if item.sketch_id == sketch.sketch_id
        )
        records = prepare_curve_identity_upgrade(current, (entity.entity_id,))
        loaded.bus.execute(
            "drawing.curve_identity.upgrade",
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "records": [record.to_mapping() for record in records],
            },
            "local",
        )
    current = next(item for item in services.kernel.sketches if item.sketch_id == first.sketch_id)
    member_before = next(
        item for item in services.kernel.sketches if item.sketch_id == second.sketch_id
    )
    source_current, target_current = current.entities[0], member_before.entities[0]
    assert isinstance(source_current, PolylineEntity) and isinstance(target_current, PolylineEntity)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 25),
        (0, 20),
        attachment=DatumAttachment(
            second.sketch_id, SketchGeometryReference(target.entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    order = (0, 3, 2, 1)
    reversed_source = replace(
        source_current,
        points_mm=tuple(source_current.points_mm[i] for i in order),
        point_ids=tuple(source_current.point_ids[i] for i in order),
    )
    state = replace(current, entities=(reversed_source,)).to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, order, 4, True)
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": current.sketch_id,
                    "base_state_sha256": current.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ],
            "polyline_topology_maps": [
                {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
            ],
        },
        "local",
        version=64,
    )
    member_after = next(
        item for item in services.kernel.sketches if item.sketch_id == second.sketch_id
    )
    updated = member_after.entities[0]
    assert isinstance(updated, PolylineEntity)
    assert updated.point_ids == tuple(target_current.point_ids[i] for i in order)
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx((0, 20))
    loaded.bus.undo()
    assert (
        next(item for item in services.kernel.sketches if item.sketch_id == second.sketch_id)
        == member_before
    )


@pytest.mark.parametrize("independent", [False, True])
def test_array_extra_output_reorder_preserves_point_ids_and_datum(
    tmp_path: Path, independent: bool
) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    member = replace(
        source, entity_id=uuid4().hex, points_mm=tuple((x + 5, y) for x, y in source.points_mm)
    )
    extra = replace(
        source, entity_id=uuid4().hex, points_mm=tuple((x + 5, y + 20) for x, y in source.points_mm)
    )
    extra_source = replace(
        source, entity_id=uuid4().hex, points_mm=tuple((x + 30, y) for x, y in source.points_mm)
    )
    sketches = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,))
        for item in (source, member, extra, extra_source)
    )
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(
        ArrayEntityRef(sketch.sketch_id, sketch.entities[0].entity_id) for sketch in sketches
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketches[0].frame,
        1,
        2,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1),),
        extra_outputs=(
            ArrayExtraOutput(refs[3] if independent else refs[0], refs[2], refs[0], 0, 1, (0, -20)),
        ),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local", version=14)
    for sketch in sketches:
        current = next(
            item for item in services.kernel.sketches if item.sketch_id == sketch.sketch_id
        )
        records = prepare_curve_identity_upgrade(current, (sketch.entities[0].entity_id,))
        loaded.bus.execute(
            "drawing.curve_identity.upgrade",
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "records": [record.to_mapping() for record in records],
            },
            "local",
        )
    extra_before = next(
        item for item in services.kernel.sketches if item.sketch_id == sketches[2].sketch_id
    ).entities[0]
    assert isinstance(extra_before, PolylineEntity)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (8, 25),
        (7.5, 20),
        attachment=DatumAttachment(
            sketches[2].sketch_id, SketchGeometryReference(extra.entity_id, "segment", 0), 0.25, 4
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    selected = sketches[3] if independent else sketches[0]
    current = next(
        item for item in services.kernel.sketches if item.sketch_id == selected.sketch_id
    )
    original = current.entities[0]
    assert isinstance(original, PolylineEntity)
    order = (0, 3, 2, 1)
    changed = replace(
        original,
        points_mm=tuple(original.points_mm[i] for i in order),
        point_ids=tuple(original.point_ids[i] for i in order),
    )
    state = replace(current, entities=(changed,)).to_state_mapping()
    mapping = PolylineTopologyMap(original.entity_id, order, 4, True)
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": current.sketch_id,
                    "base_state_sha256": current.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ],
            "polyline_topology_maps": [
                {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
            ],
        },
        "local",
        version=64,
    )
    updated_extra = next(
        item for item in services.kernel.sketches if item.sketch_id == sketches[2].sketch_id
    ).entities[0]
    assert isinstance(updated_extra, PolylineEntity)
    assert updated_extra.point_ids == tuple(extra_before.point_ids[i] for i in order)
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.attachment is not None and moved.attachment.reference.index == 3
    assert moved.target_mm == pytest.approx((7.5, 20))
    after = services.kernel.sketches
    loaded.bus.undo()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo()
    path = tmp_path / f"extra-identities-{independent}.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=())
    app.open_app_document(restored, path)
    assert restored.kernel.sketches == after
    assert restored.kernel.drawing_datum_identifiers == (moved,)


def test_cross_tangency_preserves_curve_points_and_rejects_forged_ids(tmp_path: Path) -> None:
    from copy import deepcopy

    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance_topology import new_curve_point_identities
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    curve_id = uuid4().hex
    point_ids = new_curve_point_identities(curve_id, "polyline", 3)
    curve = PolylineEntity(curve_id, ((0, 0), (10, 0), (10, 10)), point_ids=point_ids)
    circle = CircleEntity(uuid4().hex, (5, 4), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, first, session_identity=1)
    app.commit_new_sketch(services, loaded, second, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, curve.entity_id, segment_index=0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    original, solved = app.prepare_cross_sketch_tangency(services, relation)
    revisions = list(app.build_tangency_revisions(original, solved))
    params = {"relation": relation.to_mapping(), "revisions": revisions}
    history = tuple(loaded.document.commands)
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.tangency.add", params, "local", version=12)
    forged = deepcopy(params)
    for revision in cast("list[dict[str, object]]", forged["revisions"]):
        for entity in cast("list[dict[str, object]]", revision["entities"]):
            if entity["entity_id"] == curve_id:
                cast("list[str]", entity["point_ids"])[0] = uuid4().hex
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.tangency.add", forged, "local", version=13)
    assert tuple(loaded.document.commands) == history and services.kernel.sketches == (
        first,
        second,
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    assert loaded.document.commands[-1].version == 13
    result = services.kernel.sketches
    assert (
        isinstance(result[0].entities[0], PolylineEntity)
        and result[0].entities[0].point_ids == point_ids
    )
    path = tmp_path / "curve-identities-tangency.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == result and restored.kernel.cross_sketch_tangencies == (
        relation,
    )
    reopened.bus.undo_operation()
    assert (
        restored.kernel.sketches == (first, second) and not restored.kernel.cross_sketch_tangencies
    )
    reopened.bus.redo_operation()
    assert restored.kernel.sketches == result and restored.kernel.cross_sketch_tangencies == (
        relation,
    )


def test_curve_identity_tangency_and_group_survive_later_sketch_rebuild(tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.geometric_tolerance_topology import new_curve_point_identities
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    curve_id = uuid4().hex
    point_ids = new_curve_point_identities(curve_id, "polyline", 3)
    curve = PolylineEntity(curve_id, ((0, 0), (10, 0), (10, 10)), point_ids=point_ids)
    circle = CircleEntity(uuid4().hex, (5, 4), 2)
    other = LineEntity(uuid4().hex, (20, 0), (30, 0))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    third = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other,))
    for sketch in (first, second, third):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", curve_id, first.sketch_id),), selectable=False
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, curve_id, segment_index=0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = app.drawing_collection_snapshot(services)
    changed = replace(other, end_mm=(35, 0))
    updated = replace(third, entities=(changed,))
    state = updated.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": third.sketch_id,
                    "base_state_sha256": third.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=79,
    )
    after = app.drawing_collection_snapshot(services)
    assert after.groups == (group,) and after.cross_tangencies == (relation,)
    updated_curve = next(
        item for item in after.sketches if item.sketch_id == first.sketch_id
    ).entities[0]
    assert isinstance(updated_curve, PolylineEntity) and updated_curve.point_ids == point_ids
    assert next(item for item in after.sketches if item.sketch_id == third.sketch_id) == updated
    path = tmp_path / "curve-tangency-rebuild.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert app.drawing_collection_snapshot(restored) == after
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(restored) == before
    reopened.bus.undo_operation()
    assert not restored.kernel.cross_sketch_tangencies and restored.kernel.drawing_groups == (
        group,
    )
    reopened.bus.redo_operation()
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(restored) == after
