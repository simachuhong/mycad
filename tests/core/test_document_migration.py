# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Mixed legacy archives split into independently replayable source and drawing."""

from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.drawing import DrawingView, SourceBinding
from mycad.core.drawing_codec import drawing_object_mapping
from mycad.core.persistence import document_payload, save_document
from mycad.core.sketch import CircleEntity, Sketch, SketchSupportFace, WorkPlaneFrame


def test_legacy_mixed_archive_migrates_without_touching_original(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    original = app.new_document(services)
    original.bus.execute("feature.box", {"size_x": 10, "size_y": 20, "size_z": 30}, "local")
    original.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())}, "local")
    payload = document_payload(original.document)
    target = tmp_path / "legacy.mc.json"
    save_document(original.document, target)
    before = target.read_bytes()

    candidates = app.open_session_documents(services, target)

    assert [loaded.document.document_kind for _services, loaded in candidates] == [
        "part",
        "drawing",
    ]
    model_services, model = candidates[0]
    drawing_services, drawing = candidates[1]
    assert drawing.document.document_kind == "drawing"
    assert len(model_services.kernel.body_ids) == 1
    assert len(drawing_services.kernel.drawing_state.sheets) == 1
    assert drawing_services.kernel.document_references[0].file_id == model.document.file_id
    assert target.read_bytes() == before
    for _services, loaded in candidates:
        assert document_payload(loaded.document)["migration_origin"] == payload


def test_legacy_standalone_drawing_keeps_its_kind(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    target = tmp_path / "old.my2d"
    save_document(loaded.document, target)
    candidates = app.open_session_documents(services, target)
    assert len(candidates) == 1
    assert candidates[0][1].document.document_kind == "sketch"


def test_legacy_sketch_views_preserve_dashed_source_identities(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    sketch = Sketch(str(uuid4()), WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)}, "local")
    loaded.bus.execute(
        "drawing.view.create",
        drawing_object_mapping(
            DrawingView(uuid4(), sheet, SourceBinding("sketch", sketch.sketch_id))
        ),
        "local",
    )
    path = tmp_path / "old.my2d"
    save_document(loaded.document, path)
    candidates = app.open_session_documents(services, path)
    drawing_services, _drawing = candidates[-1]
    assert drawing_services.kernel.sketches[0].sketch_id == sketch.sketch_id
    assert drawing_services.kernel.drawing_state.views[0].source.sketch_id == sketch.sketch_id


@pytest.mark.parametrize("with_sketch,expected_version", [(False, 1), (True, 2)])
def test_early_archives_migrate_with_audit_and_original_bytes(
    tmp_path: Path, with_sketch: bool, expected_version: int
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 5, "size_y": 6, "size_z": 7}, "local")
    if with_sketch:
        sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 2),))
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=1), "local", version=1)
    assert loaded.document.archive_version == expected_version
    path = tmp_path / "early.mc.json"
    save_document(loaded.document, path)
    before = path.read_bytes()
    bundle = app.open_session_bundle(services, path)
    assert bundle.migrated
    migrated = bundle.documents[0][1].document
    assert document_payload(migrated)["migration_origin"] == document_payload(loaded.document)
    assert path.read_bytes() == before
    assert migrated.commands == loaded.document.commands


def test_attached_internal_sketch_survives_interleaved_paper_migration(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 30, "size_z": 8}, "local")
    face = services.kernel.viewport_data()[-1].faces[0]
    descriptor = services.kernel.interactive_face_selector(face.topology_id)
    frame = services.kernel.interactive_face_frame(face.topology_id)
    sketch = Sketch(
        uuid4().hex,
        WorkPlaneFrame.from_planar_face(frame.origin, frame.normal),
        (CircleEntity(uuid4().hex, (0, 0), 2),),
        support_face=SketchSupportFace.from_mapping(descriptor),
    )
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())}, "local")
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    path = tmp_path / "attached.my3d"
    save_document(loaded.document, path)
    bundle = app.open_session_bundle(services, path)
    model_services, model = bundle.documents[0]
    drawing_services, _drawing = bundle.documents[1]
    assert model_services.kernel.sketches == (sketch,)
    assert drawing_services.kernel.sketches == (sketch,)
    assert [command.ordinal for command in model.document.commands] == [0, 1]
    assert model.document.commands[1].timestamp_utc == loaded.document.commands[2].timestamp_utc
    isolated, separated = app.separate_internal_sketch(model_services, sketch.sketch_id)
    assert isolated.kernel.sketches[0].support_face is None
    assert isolated.kernel.sketches[0].frame == sketch.frame
    assert separated.document.document_kind == "sketch"
