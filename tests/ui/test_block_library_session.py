# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Block library actions remain isolated from draft and document histories."""

from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.block_library import AssetMetadata
from mycad.core.block_library_import import BlockPlacement
from mycad.core.drawing_blocks import BlockDefinition
from mycad.core.exceptions import ValidationError
from mycad.core.replay_proposal import ReplayAppend
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.libraries.block_store import BlockLibraryStore, LibraryRoot
from mycad.ui.block_library_controller import BlockLibraryController
from mycad.ui.drawing_collection_session import DrawingCollectionSession


def test_draft_export_and_import_cancel(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, sketch.to_state_mapping(), "local"),
        session_identity=1,
    )
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    session.stage(ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"))
    store = BlockLibraryStore((LibraryRoot("local", tmp_path / "lib", False),), tmp_path / "cache")
    controller = BlockLibraryController(
        store,
        lambda: session.snapshot,
        session.checkpoint,
        session.stage,
        session.preview_operation,
    )
    history = tuple(loaded.document.commands)
    controller.save_definition(definition.definition_id, AssetMetadata("B", "", ()), "local", "")
    assert tuple(loaded.document.commands) == history
    entry = store.scan("local").entries[0]
    preview = controller.prepare_import(entry, BlockPlacement((3, 0), 0, 1, "0"))
    controller.confirm_import(preview)
    assert len(session.snapshot.block_instances) == 1
    session.undo()
    assert not session.snapshot.block_instances
    session.redo()
    assert len(session.snapshot.block_instances) == 1
    session.cancel()
    assert not loaded.document.commands
    assert store.read(entry).name == "B"


def test_preview_rejects_changed_context_and_cancel(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, sketch.to_state_mapping(), "local"),
        session_identity=1,
    )
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    session.stage(ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"))
    store = BlockLibraryStore((LibraryRoot("local", tmp_path / "lib", False),), tmp_path / "cache")
    controller = BlockLibraryController(
        store,
        lambda: session.snapshot,
        session.checkpoint,
        session.stage,
        session.preview_operation,
    )
    controller.save_definition(definition.definition_id, AssetMetadata("B", "", ()), "local", "")
    entry = store.scan("local").entries[0]
    preview = controller.prepare_import(entry, BlockPlacement((3, 0), 0, 1, "0"))
    controller.cancel_import()
    with pytest.raises(ValidationError):
        controller.confirm_import(preview)
    assert not session.snapshot.block_instances
    preview = controller.prepare_import(entry, None)
    session.undo()
    with pytest.raises(ValidationError):
        controller.confirm_import(preview)
    assert not session.snapshot.block_definitions
    session.cancel()


def test_reposition_preview_keeps_frozen_ids_and_stages_final_point(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, sketch.to_state_mapping(), "local"),
        session_identity=1,
    )
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    session.stage(ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"))
    store = BlockLibraryStore((LibraryRoot("local", tmp_path / "lib", False),), tmp_path / "cache")
    controller = BlockLibraryController(
        store,
        lambda: session.snapshot,
        session.checkpoint,
        session.stage,
        session.preview_operation,
    )
    controller.save_definition(definition.definition_id, AssetMetadata("B", "", ()), "local", "")
    preview = controller.prepare_import(
        store.scan("local").entries[0], BlockPlacement((1, 1), 0, 1, "0")
    )
    moved = controller.reposition_preview(preview, BlockPlacement((8, 9), 35, 2, "0"))
    assert moved.prepared.instance_id == preview.prepared.instance_id
    assert moved.prepared.definition_id == preview.prepared.definition_id
    assert moved.candidate.block_instances[-1].insertion_mm == (8, 9)
    with pytest.raises(ValidationError):
        controller.confirm_import(preview)
    controller.confirm_import(moved)
    assert session.snapshot.block_instances[-1].insertion_mm == (8, 9)
    session.cancel()


def test_preview_rejects_document_switch_without_writes(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    identity = [1]
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, sketch.to_state_mapping(), "local"),
        session_identity=1,
        session_identity_provider=lambda: identity[0],
    )
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    session.stage(ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"))
    store = BlockLibraryStore((LibraryRoot("local", tmp_path / "lib", False),), tmp_path / "cache")
    controller = BlockLibraryController(
        store,
        lambda: session.snapshot,
        session.checkpoint,
        session.stage,
        session.preview_operation,
    )
    controller.save_definition(definition.definition_id, AssetMetadata("B", "", ()), "local", "")
    preview = controller.prepare_import(
        store.scan("local").entries[0], BlockPlacement((0, 0), 0, 1, "0")
    )
    identity[0] = 2
    with pytest.raises(ValidationError, match="会话"):
        controller.confirm_import(preview)
    assert not loaded.document.commands
    identity[0] = 1
    assert not session.snapshot.block_instances
    session.cancel()
