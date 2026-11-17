# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""New and legacy drawings retain their own replayable fillet baselines."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.document import Document
from mycad.core.document_kinds import DocumentKind
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import document_payload, save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.schema_v6 import validate_archive_v6
from mycad.core.schema_v7 import validate_archive_v7
from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame


def test_v7_schema_validates_baseline_without_changing_v6() -> None:
    services = app.build_app(discoverers=[])
    document = Document(services.registry, archive_version=6, document_type="drawing2d")
    old = document_payload(document)
    candidate = {**old, "version": 7, "drawing_defaults": {"fillet_radius": 0}}
    validate_archive_v7(candidate)
    with pytest.raises(ValidationError):
        validate_archive_v6({**old, "drawing_defaults": {"fillet_radius": 0}})
    for bad in (None, True, -1, float("nan"), float("inf"), 10**1000, "0"):
        with pytest.raises(ValidationError):
            validate_archive_v7({**candidate, "drawing_defaults": {"fillet_radius": bad}})


def test_document_baseline_is_immutable_and_legacy_safe() -> None:
    services = app.build_app(discoverers=[])
    document = Document(
        services.registry, archive_version=7, document_type="drawing2d", drawing_fillet_baseline=0
    )
    assert document.drawing_fillet_baseline == 0
    with pytest.raises(ValidationError):
        Document(
            services.registry,
            archive_version=6,
            document_type="drawing2d",
            drawing_fillet_baseline=0,
        )
    with pytest.raises(ValidationError):
        Document(services.registry, archive_version=7, drawing_fillet_baseline=0)


@pytest.mark.parametrize("kind", ["sketch", "drawing"])
def test_new_workspace_uses_zero_baseline_without_history(
    kind: DocumentKind, tmp_path: Path
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind=kind)
    assert loaded.document.archive_version == 8
    assert loaded.document.drawing_fillet_baseline == 0
    assert services.kernel.drawing_fillet_radius == 0
    assert not loaded.document.commands and not loaded.document.is_dirty
    path = tmp_path / "empty.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert reopened.document.drawing_fillet_baseline == 0
    assert services.kernel.drawing_fillet_radius == 0


def test_explicit_v7_baseline_roundtrips_and_replays(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    document = Document(
        services.registry, archive_version=7, document_type="drawing2d", drawing_fillet_baseline=0
    )
    path = tmp_path / "explicit-v7.my2d"
    save_document(document, path)
    reopened = app.open_app_document(services, path)
    assert reopened.document.drawing_fillet_baseline == 0
    assert services.kernel.drawing_fillet_radius == 0
    reopened.bus.execute("drawing.fillet_radius.set", {"radius": 5}, "local", version=1)
    reopened.bus.undo()
    assert services.kernel.drawing_fillet_radius == 0
    reopened.bus.redo()
    assert services.kernel.drawing_fillet_radius == 5
    candidate = app.create_replay_candidate(services, reopened, session_identity=0)
    candidate.stage(
        ReplayChangeSet(
            (), (ReplayAppend("drawing.fillet_radius.set", 1, {"radius": 6}, "local"),), False
        ),
        current_session_identity=0,
    )
    preview = candidate.preview(current_session_identity=0)
    assert preview.state == "succeeded", preview.failure
    grant = candidate.authorize_commit(current_session_identity=0)
    candidate.commit(grant, current_session_identity=0)
    assert services.kernel.drawing_fillet_radius == 6
    reopened.bus.undo()
    reopened.bus.undo()
    assert services.kernel.drawing_fillet_radius == 0


def test_new_drawing_fillet_baseline_survives_save_undo_and_redo(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    assert loaded.document.archive_version == 8
    assert not loaded.document.commands
    assert services.kernel.drawing_fillet_radius == 0
    loaded.bus.execute("drawing.fillet_radius.set", {"radius": 4}, "local", version=1)
    loaded.bus.undo()
    assert services.kernel.drawing_fillet_radius == 0
    loaded.bus.redo()
    path = tmp_path / "new.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_fillet_radius == 4
    reopened.bus.undo()
    assert services.kernel.drawing_fillet_radius == 0
    reopened.bus.redo()
    assert services.kernel.drawing_fillet_radius == 4
    _shared, copied = app.copy_app_document(services, reopened.document, source_bus=reopened.bus)
    assert copied.document.file_id != reopened.document.file_id
    assert copied.document.drawing_fillet_baseline == 0
    copy_path = tmp_path / "copy.my2d"
    save_document(copied.document, copy_path)
    copy_services = app.fork_app_services(services)
    copy_loaded = app.open_app_document(copy_services, copy_path)
    copy_loaded.bus.undo()
    assert copy_services.kernel.drawing_fillet_radius == 0


@pytest.mark.parametrize("archive_version", [3, 4, 5, 6])
def test_legacy_drawing_keeps_original_baseline(tmp_path: Path, archive_version: int) -> None:
    services = app.build_app(discoverers=[])
    legacy = Document(services.registry, archive_version=archive_version, document_type="drawing2d")
    path = tmp_path / "legacy.my2d"
    save_document(legacy, path)
    reopened = app.open_app_document(services, path)
    assert reopened.document.archive_version == archive_version
    assert services.kernel.drawing_fillet_radius == 1
    reopened.bus.execute("drawing.fillet_radius.set", {"radius": 4}, "local", version=1)
    reopened.bus.undo()
    assert services.kernel.drawing_fillet_radius == 1


def test_v7_sketch_reference_upgrades_and_replays_part(tmp_path: Path) -> None:
    source_services = app.build_app(discoverers=[])
    source_document = Document(
        source_services.registry,
        archive_version=7,
        document_type="drawing2d",
        drawing_fillet_baseline=0,
    )
    source_path = tmp_path / "source.my2d"
    save_document(source_document, source_path)
    source = app.open_app_document(source_services, source_path)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    app.commit_new_sketch(source_services, source, sketch, session_identity=0)
    reference = app.reference_parameters(source.document, object_id=sketch.sketch_id)
    direct_services = app.fork_app_services(source_services)
    direct = app.new_workspace_document(direct_services, kind="part")
    _snapshot, preview_sketches = app.preview_command_with_sketches(
        direct_services,
        (),
        "reference.attach",
        reference,
        source_archive_version=4,
        command_version=1,
        target_archive_version=7,
    )
    assert preview_sketches and not direct.document.commands
    direct.bus.execute("feature.box", {"size_x": 3, "size_y": 4, "size_z": 5}, "local")
    before = direct.document.commands
    invalid_reference = {**reference, "object_id": uuid4().hex}
    with pytest.raises(ValidationError):
        direct.bus.execute("reference.attach", invalid_reference, "local")
    assert direct.document.archive_version == 4
    assert direct.document.commands == before
    assert len(direct_services.kernel.body_ids) == 1
    direct.bus.execute("reference.attach", reference, "local")
    assert direct.document.archive_version == 7
    assert len(direct_services.kernel.sketches) == 1
    direct.bus.undo()
    assert direct.document.archive_version == 7 and not direct_services.kernel.sketches
    assert len(direct_services.kernel.body_ids) == 1
    direct.bus.redo()
    assert len(direct_services.kernel.sketches) == 1
    upgraded_commands = direct.document.commands
    assert upgraded_commands[0].timestamp_utc == before[0].timestamp_utc
    direct.bus.undo_operation()
    assert not direct_services.kernel.sketches and len(direct_services.kernel.body_ids) == 1
    direct.bus.undo_operation()
    assert not direct_services.kernel.body_ids
    direct.bus.redo_operation()
    direct.bus.redo_operation()
    assert direct.document.commands == upgraded_commands
    assert len(direct_services.kernel.body_ids) == 1 and len(direct_services.kernel.sketches) == 1
    redo_services = app.fork_app_services(source_services)
    redo_document = app.new_workspace_document(redo_services, kind="part")
    redo_document.bus.execute("feature.box", {"size_x": 3, "size_y": 4, "size_z": 5}, "local")
    redo_document.bus.undo()
    with pytest.raises(ValidationError):
        redo_document.bus.execute("reference.attach", invalid_reference, "local")
    assert redo_document.document.archive_version == 4
    redo_document.bus.redo()
    assert len(redo_services.kernel.body_ids) == 1
    part_services = app.fork_app_services(source_services)
    part = app.new_workspace_document(part_services, kind="part")
    candidate = app.create_replay_candidate(part_services, part, session_identity=0)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("reference.attach", 1, reference, "local"),),
            False,
            target_archive_version=7,
        ),
        current_session_identity=0,
    )
    preview = candidate.preview(current_session_identity=0)
    assert preview.state == "succeeded", preview.failure
    grant = candidate.authorize_commit(current_session_identity=0)
    candidate.commit(grant, current_session_identity=0)
    assert part.document.archive_version == 7
    assert len(part_services.kernel.sketches) == 1
    part_path = tmp_path / "part.my3d"
    save_document(part.document, part_path)
    reopened_services = app.fork_app_services(part_services)
    reopened = app.open_app_document(reopened_services, part_path)
    assert reopened.document.archive_version == 7
    assert len(reopened_services.kernel.sketches) == 1
    reopened.bus.undo()
    assert reopened.document.archive_version == 7
    assert not reopened_services.kernel.sketches
    reopened.bus.redo()
    assert len(reopened_services.kernel.sketches) == 1


@pytest.mark.parametrize("archive_version", [3, 4, 5, 6])
def test_legacy_candidate_upgrade_keeps_legacy_baseline(
    tmp_path: Path, archive_version: int
) -> None:
    services = app.build_app(discoverers=[])
    legacy = Document(services.registry, archive_version=archive_version, document_type="drawing2d")
    legacy_path = tmp_path / "legacy.my2d"
    save_document(legacy, legacy_path)
    loaded = app.open_app_document(services, legacy_path)
    assert loaded.document.archive_version == archive_version
    candidate = app.create_replay_candidate(services, loaded, session_identity=0)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("drawing.fillet_radius.set", 1, {"radius": 4}, "local"),),
            False,
            target_archive_version=7,
        ),
        current_session_identity=0,
    )
    preview = candidate.preview(current_session_identity=0)
    assert preview.state == "succeeded", preview.failure
    grant = candidate.authorize_commit(current_session_identity=0)
    candidate.commit(grant, current_session_identity=0)
    assert loaded.document.drawing_fillet_baseline == 1
    loaded.bus.undo()
    assert services.kernel.drawing_fillet_radius == 1
    path = tmp_path / "upgraded.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert reopened.document.archive_version == 7
    assert reopened.document.drawing_fillet_baseline == 1
    assert services.kernel.drawing_fillet_radius == 1


def test_drawing_reference_update_preserves_fillet_baseline(tmp_path: Path) -> None:
    source_services = app.build_app(discoverers=[])
    source = app.new_workspace_document(source_services, kind="part")
    source.bus.execute("feature.box", {"size_x": 3, "size_y": 4, "size_z": 5}, "local")
    services = app.fork_app_services(source_services)
    drawing = app.new_workspace_document(services, kind="drawing")
    reference = app.reference_parameters(source.document)
    drawing.bus.execute("reference.attach", reference, "local")
    assert services.kernel.drawing_fillet_radius == 0
    source.document.set_metadata("notes", "updated source")
    updated = app.reference_parameters(source.document, reference_id=str(reference["reference_id"]))
    drawing.bus.execute("reference.update", updated, "local")
    assert services.kernel.drawing_fillet_radius == 0
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 0)
    drawing.bus.execute("drawing.fillet_radius.set", {"radius": 4}, "local", version=1)
    drawing.bus.undo()
    assert services.kernel.drawing_fillet_radius == 0
    path = tmp_path / "drawing.my2d"
    save_document(drawing.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_fillet_radius == 0
    reopened.bus.undo()
    reopened.bus.redo()
    assert services.kernel.drawing_fillet_radius == 0
    reopened.bus.execute("drawing.fillet_radius.set", {"radius": 4}, "local", version=1)
    source.document.set_metadata("notes", "updated source again")
    updated_again = app.reference_parameters(
        source.document, reference_id=str(reference["reference_id"])
    )
    reopened.bus.execute("reference.update", updated_again, "local")
    assert services.kernel.drawing_fillet_radius == 4
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 0)
    reopened.bus.undo()
    reopened.bus.undo()
    assert services.kernel.drawing_fillet_radius == 0


def test_reference_update_from_v4_to_v7_preserves_old_snapshot(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    legacy = Document(services.registry, archive_version=4, document_type="drawing2d")
    source_path = tmp_path / "legacy-source.my2d"
    save_document(legacy, source_path)
    source = app.open_app_document(services, source_path)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    source.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    original_reference = app.reference_parameters(source.document, object_id=sketch.sketch_id)
    target_services = app.fork_app_services(services)
    target = app.new_workspace_document(target_services, kind="part")
    target.bus.execute("reference.attach", original_reference, "local")
    assert target.document.archive_version == 4
    candidate = app.create_replay_candidate(services, source, session_identity=0)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("drawing.fillet_radius.set", 1, {"radius": 3}, "local"),),
            False,
            target_archive_version=7,
        ),
        current_session_identity=0,
    )
    preview = candidate.preview(current_session_identity=0)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=0), current_session_identity=0
    )
    updated = app.reference_parameters(
        source.document,
        object_id=sketch.sketch_id,
        reference_id=str(original_reference["reference_id"]),
    )
    target.bus.execute("reference.update", updated, "local")
    assert target.document.archive_version == 7
    assert target_services.kernel.document_references[0].fingerprint == updated["fingerprint"]
    target.bus.undo()
    assert (
        target_services.kernel.document_references[0].fingerprint
        == original_reference["fingerprint"]
    )
    target.bus.redo()
    assert target_services.kernel.document_references[0].fingerprint == updated["fingerprint"]
    target_path = tmp_path / "target.my3d"
    save_document(target.document, target_path)
    restored = app.fork_app_services(target_services)
    app.open_app_document(restored, target_path)
    assert restored.kernel.document_references[0].fingerprint == updated["fingerprint"]


def test_invalid_v7_baseline_does_not_replace_open_document(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    loaded.bus.execute("drawing.fillet_radius.set", {"radius": 4}, "local", version=1)
    document = Document(
        services.registry, archive_version=7, document_type="drawing2d", drawing_fillet_baseline=0
    )
    payload = document_payload(document)
    payload["drawing_defaults"] = {"fillet_radius": -1}
    path = tmp_path / "invalid-v7.my2d"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError):
        app.open_app_document(services, path)
    assert services.kernel.drawing_fillet_radius == 4
    assert loaded.document.command_count == 1
