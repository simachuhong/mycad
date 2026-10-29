# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Cross-document snapshots remain replayable without external files."""

from __future__ import annotations

from math import pi
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.exceptions import ValidationError
from mycad.core.measurements import MeasurementRequest
from mycad.core.persistence import save_document
from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame


def source_sketch(services: app.AppServices) -> app.LoadedDocument:
    loaded = app.new_workspace_document(services, kind="sketch")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    return loaded


def test_linked_sketch_extrudes_reopens_and_detaches(tmp_path: Path) -> None:
    source_services = app.build_app(discoverers=[])
    source = source_sketch(source_services)
    services = app.fork_app_services(source_services)
    model = app.new_workspace_document(services, kind="part")
    reference = app.reference_parameters(
        source.document, object_id=source_services.kernel.sketches[0].sketch_id
    )
    model.bus.execute("reference.attach", reference, "local")
    instance = services.kernel.sketches[0]
    assert instance.sketch_id != source_services.kernel.sketches[0].sketch_id
    model.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": instance.sketch_id}, "distance": 8.0},
        "local",
    )
    assert len(services.kernel.body_ids) == 1
    target = tmp_path / "part.my3d"
    save_document(model.document, target)
    reopened_services = app.fork_app_services(services)
    reopened = app.open_app_document(reopened_services, target)
    assert len(reopened_services.kernel.body_ids) == 1
    assert reopened_services.kernel.linked_sketch_ids == frozenset({instance.sketch_id})
    reopened.bus.execute("reference.detach", {"reference_id": reference["reference_id"]}, "local")
    assert reopened_services.kernel.linked_sketch_ids == frozenset()
    reopened.bus.undo()
    assert instance.sketch_id in reopened_services.kernel.linked_sketch_ids


def test_reference_update_rebuilds_consumers_and_undo_restores() -> None:
    src_services = app.build_app(discoverers=[])
    src = source_sketch(src_services)
    services = app.fork_app_services(src_services)
    target = app.new_workspace_document(services, kind="part")
    params = app.reference_parameters(
        src.document, object_id=src_services.kernel.sketches[0].sketch_id
    )
    target.bus.execute("reference.attach", params, "local")
    instance_id = services.kernel.sketches[0].sketch_id
    target.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": instance_id}, "distance": 4},
        "local",
    )
    with pytest.raises(ValidationError, match="关联|linked"):
        services.kernel.apply("sketch.constraint.update", {"sketch_id": instance_id})
    original_sketch = src_services.kernel.sketches[0]
    revised = Sketch(
        original_sketch.sketch_id,
        original_sketch.frame,
        (CircleEntity(original_sketch.entities[0].entity_id, (0, 0), 7),),
    )
    src.bus.edit_and_replay(0, revised.to_mapping(version=3), "local", "change radius")
    updated = app.reference_parameters(
        src.document,
        object_id=src_services.kernel.sketches[0].sketch_id,
        reference_id=str(params["reference_id"]),
    )
    target.bus.execute("reference.update", updated, "local")
    assert len(services.kernel.body_ids) == 1
    assert services.kernel.document_references[0].fingerprint == updated["fingerprint"]
    measured = services.kernel.measure(
        MeasurementRequest("body_volume", services.kernel.geometry_revision)
    )
    assert measured.value == pytest.approx(pi * 49 * 4)
    target.bus.undo()
    assert services.kernel.document_references[0].fingerprint == params["fingerprint"]
    measured = services.kernel.measure(
        MeasurementRequest("body_volume", services.kernel.geometry_revision)
    )
    assert measured.value == pytest.approx(pi * 25 * 4)


def test_reference_wrong_file_identity_rejected_without_losing_model() -> None:
    services = app.build_app(discoverers=[])
    src_services = app.fork_app_services(services)
    src = source_sketch(src_services)
    target = app.new_workspace_document(services, kind="part")
    params = app.reference_parameters(
        src.document, object_id=src_services.kernel.sketches[0].sketch_id
    )
    params["file_id"] = uuid4().hex
    with pytest.raises(ValidationError, match="identity|file_id"):
        target.bus.execute("reference.attach", params, "local")
    assert target.document.commands == ()


def test_repeated_reference_updates_preserve_history_snapshot_slots() -> None:
    src_services = app.build_app(discoverers=[])
    src = source_sketch(src_services)
    services = app.fork_app_services(src_services)
    target = app.new_workspace_document(services, kind="part")
    object_id = src_services.kernel.sketches[0].sketch_id
    params = app.reference_parameters(src.document, object_id=object_id)
    target.bus.execute("reference.attach", params, "local")
    for note in ("first", "second"):
        src.document.set_metadata("notes", note)
        update = app.reference_parameters(
            src.document, object_id=object_id, reference_id=str(params["reference_id"])
        )
        target.bus.execute("reference.update", update, "local")
    assert len(services.kernel.viewport_state_ids()) == len(target.document.commands)
