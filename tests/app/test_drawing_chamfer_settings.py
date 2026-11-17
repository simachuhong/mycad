# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drawing chamfer values are reconstructed by the command bus."""

from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.document import Document
from mycad.core.exceptions import InvalidHistoryError, ValidationError
from mycad.core.persistence import document_payload, save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.schema_v7 import validate_archive_v7
from mycad.core.schema_v8 import validate_archive_v8
from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame


def test_v8_chamfer_baseline_schema_and_old_schema_isolation() -> None:
    services = app.build_app(discoverers=[])
    old = document_payload(
        Document(services.registry, archive_version=7, document_type="drawing2d")
    )
    defaults = {"fillet_radius": 0, "chamfer_angle": 0}
    current = {**old, "version": 8, "drawing_defaults": defaults}
    validate_archive_v8(current)
    with pytest.raises(ValidationError):
        validate_archive_v7({**old, "drawing_defaults": defaults})
    for value in (None, True, -1, 180, float("inf"), float("nan"), 10**1000, "0"):
        with pytest.raises(ValidationError):
            validate_archive_v8(
                {**current, "drawing_defaults": {**defaults, "chamfer_angle": value}}
            )


def test_new_drawing_chamfer_baseline_roundtrips_and_undoes(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="drawing")
    assert loaded.document.archive_version == 8
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 0)
    path = tmp_path / "new.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.execute(
        "drawing.chamfer_values.set",
        {"distance_first": 2, "distance_second": 3, "angle_length": 4, "angle": 30},
        "local",
        version=1,
    )
    reopened.bus.undo()
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 0)
    reopened.bus.redo()
    assert services.kernel.drawing_chamfer_values == (2, 3, 4, 30)


@pytest.mark.parametrize("version", [3, 4, 5, 6, 7])
def test_old_drawing_chamfer_baseline_remains_45(tmp_path: Path, version: int) -> None:
    services = app.build_app(discoverers=[])
    document = Document(services.registry, archive_version=version, document_type="drawing2d")
    path = tmp_path / "old.my2d"
    save_document(document, path)
    loaded = app.open_app_document(services, path)
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 45)
    loaded.bus.execute(
        "drawing.chamfer_values.set",
        {"distance_first": 2, "distance_second": 3, "angle_length": 4, "angle": 30},
        "local",
        version=1,
    )
    loaded.bus.undo()
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 45)


def test_v8_upgrade_keeps_legacy_chamfer_baseline(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    old = Document(services.registry, archive_version=7, document_type="drawing2d")
    path = tmp_path / "old.my2d"
    save_document(old, path)
    loaded = app.open_app_document(services, path)
    candidate = app.create_replay_candidate(services, loaded, session_identity=0)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("drawing.fillet_radius.set", 1, {"radius": 2}, "local"),),
            False,
            target_archive_version=8,
        ),
        current_session_identity=0,
    )
    result = candidate.preview(current_session_identity=0)
    assert result.state == "succeeded", result.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=0), current_session_identity=0
    )
    assert loaded.document.drawing_chamfer_angle_baseline == 45
    loaded.bus.undo()
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 45)


def test_v8_sketch_reference_upgrades_part_and_reopens(tmp_path: Path) -> None:
    source_services = app.build_app(discoverers=[])
    source = app.new_workspace_document(source_services, kind="sketch")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    app.commit_new_sketch(source_services, source, sketch, session_identity=0)
    reference = app.reference_parameters(source.document, object_id=sketch.sketch_id)
    services = app.fork_app_services(source_services)
    part = app.new_workspace_document(services, kind="part")
    part.bus.execute("feature.box", {"size_x": 3, "size_y": 4, "size_z": 5}, "local")
    before = part.document.commands
    with pytest.raises(ValidationError):
        part.bus.execute("reference.attach", {**reference, "object_id": uuid4().hex}, "local")
    assert part.document.archive_version == 4 and part.document.commands == before
    assert len(services.kernel.body_ids) == 1
    part.bus.execute("reference.attach", reference, "local")
    assert part.document.archive_version == 8 and len(services.kernel.sketches) == 1
    part.bus.undo()
    assert not services.kernel.sketches and len(services.kernel.body_ids) == 1
    part.bus.redo()
    path = tmp_path / "part.my3d"
    save_document(part.document, path)
    app.open_app_document(services, path)
    assert len(services.kernel.sketches) == 1


def test_v8_copy_preserves_chamfer_baseline_on_replay(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    original = app.new_workspace_document(services, kind="drawing")
    original.bus.execute(
        "drawing.chamfer_values.set",
        {"distance_first": 2, "distance_second": 3, "angle_length": 4, "angle": 30},
        "local",
        version=1,
    )
    _services, copied = app.copy_app_document(services, original.document, source_bus=original.bus)
    path = tmp_path / "copy.my2d"
    save_document(copied.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo()
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 0)


def test_v8_nested_reference_update_preserves_drawing_baselines(tmp_path: Path) -> None:
    source_services = app.build_app(discoverers=[])
    source = app.new_workspace_document(source_services, kind="sketch")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    app.commit_new_sketch(source_services, source, sketch, session_identity=0)
    part_services = app.fork_app_services(source_services)
    part = app.new_workspace_document(part_services, kind="part")
    part.bus.execute("feature.box", {"size_x": 3, "size_y": 4, "size_z": 5}, "local")
    part.bus.execute(
        "reference.attach",
        app.reference_parameters(source.document, object_id=sketch.sketch_id),
        "local",
    )
    services = app.fork_app_services(part_services)
    drawing = app.new_workspace_document(services, kind="drawing")
    reference = app.reference_parameters(part.document)
    drawing.bus.execute("reference.attach", reference, "local")
    part.document.set_metadata("notes", "changed")
    updated = app.reference_parameters(part.document, reference_id=str(reference["reference_id"]))
    drawing.bus.execute("reference.update", updated, "local")
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 0)
    assert services.kernel.drawing_fillet_radius == 0
    path = tmp_path / "nested.my2d"
    save_document(drawing.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo()
    reopened.bus.redo()
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 0)
    assert services.kernel.drawing_fillet_radius == 0


def test_engineering_drawing_preview_replays_part_reference() -> None:
    source_services = app.build_app(discoverers=[])
    part = app.new_workspace_document(source_services, kind="part")
    part.bus.execute("feature.box", {"size_x": 3, "size_y": 4, "size_z": 5}, "local")
    services = app.fork_app_services(source_services)
    drawing = app.new_workspace_document(services, kind="drawing")
    drawing.bus.execute("reference.attach", app.reference_parameters(part.document), "local")
    commands = drawing.document.commands
    viewport, _sketches = app.preview_command_with_sketches(
        services,
        commands,
        "drawing.fillet_radius.set",
        {"radius": 2},
        source_archive_version=drawing.document.archive_version,
        source_document_type=drawing.document.document_type,
        source_document_kind=drawing.document.document_kind,
        source_drawing_fillet_baseline=drawing.document.drawing_fillet_baseline,
        source_drawing_chamfer_angle_baseline=drawing.document.drawing_chamfer_angle_baseline,
    )
    assert viewport is not None
    assert drawing.document.commands == commands
    assert services.kernel.drawing_fillet_radius == 0


def test_chamfer_values_save_reopen_undo_and_redo(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 0)
    values = {"distance_first": 2, "distance_second": 3, "angle_length": 4, "angle": 30}
    loaded.bus.execute("drawing.chamfer_values.set", values, "local", version=1)
    assert services.kernel.drawing_chamfer_values == (2, 3, 4, 30)
    path = tmp_path / "chamfer.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_chamfer_values == (2, 3, 4, 30)
    reopened.bus.undo()
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 0)
    reopened.bus.redo()
    assert services.kernel.drawing_chamfer_values == (2, 3, 4, 30)


def test_legacy_drawing_without_chamfer_command_uses_previous_defaults(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    legacy = Document(services.registry, archive_version=7, document_type="drawing2d")
    path = tmp_path / "legacy.my2d"
    save_document(legacy, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_chamfer_values == (0, 0, 0, 45)


@pytest.mark.parametrize("bad", [-1.0, float("inf"), float("nan"), True])
def test_invalid_chamfer_values_do_not_modify_document(bad: object) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.chamfer_values.set",
            {"distance_first": bad, "distance_second": 3, "angle_length": 4, "angle": 30},
            "local",
            version=1,
        )
    assert not loaded.document.commands


def test_chamfer_angle_outside_range_is_rejected() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.chamfer_values.set",
            {"distance_first": 2, "distance_second": 3, "angle_length": 4, "angle": 180},
            "local",
            version=1,
        )
    assert not loaded.document.commands


def test_chamfer_values_rejected_in_part_document() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services)
    with pytest.raises(ValidationError, match="二维"):
        loaded.bus.execute(
            "drawing.chamfer_values.set",
            {"distance_first": 2, "distance_second": 3, "angle_length": 4, "angle": 30},
            "local",
            version=1,
        )
    assert not loaded.document.commands


def test_undo_before_settings_rejects_unrelated_or_stale_history() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    for y in (0, 10):
        sketch = Sketch(
            uuid4().hex,
            WorkPlaneFrame.xy(),
            (LineEntity(uuid4().hex, (0, y), (10, y)),),
        )
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = loaded.document.commands[-2].instance_id
    assert target is not None
    loaded.bus.execute(
        "drawing.chamfer_values.set",
        {"distance_first": 2, "distance_second": 3, "angle_length": 4, "angle": 30},
        "local",
        version=1,
    )
    before = loaded.document.commands
    with pytest.raises(InvalidHistoryError):
        loaded.bus.undo_operation_before_drawing_settings(target, loaded.document.revision - 1)
    assert loaded.document.commands == before
    with pytest.raises(InvalidHistoryError):
        loaded.bus.undo_operation_before_drawing_settings(target, loaded.document.revision)
    assert loaded.document.commands == before and len(services.kernel.sketches) == 2
    with pytest.raises(InvalidHistoryError):
        loaded.bus.undo_operation_before_drawing_settings("missing", loaded.document.revision)
    assert loaded.document.commands == before


def test_undo_before_settings_rebuild_failure_rolls_back_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (10, 0)),))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = loaded.document.commands[-1].instance_id
    assert target is not None
    loaded.bus.execute(
        "drawing.chamfer_values.set",
        {"distance_first": 2, "distance_second": 3, "angle_length": 4, "angle": 30},
        "local",
        version=1,
    )
    before = loaded.document.commands
    rebuild_attribute = "_rebuild"
    original_rebuild = cast("Callable[[], None]", getattr(loaded.bus, rebuild_attribute))
    calls = 0

    def fail_once() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated replay failure")
        original_rebuild()

    monkeypatch.setattr(loaded.bus, "_rebuild", fail_once)
    with pytest.raises(RuntimeError, match="simulated replay failure"):
        loaded.bus.undo_operation_before_drawing_settings(target, loaded.document.revision)
    assert loaded.document.commands == before and services.kernel.sketches == (sketch,)
    assert loaded.bus.is_healthy
    loaded.bus.undo_operation_before_drawing_settings(target, loaded.document.revision)
    assert not services.kernel.sketches
    assert services.kernel.drawing_chamfer_values == (2, 3, 4, 30)
