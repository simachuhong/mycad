# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Real kernel contexts survive files, previews and isolated regeneration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from math import pi
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.command_identity import ExecutionContext
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import document_payload, save_document
from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.geom.kernel import BuildKernel


def test_real_rebuild_save_as_open_and_continue_preserve_ids(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 4})
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    identity = loaded.document.commands[0].instance_id
    assert services.kernel.execution_contexts[0].instance_id == identity
    loaded.bus.edit_and_replay(0, {"size_x": 22, "size_y": 20, "size_z": 4}, "local", "resize")
    _services, copied = app.copy_app_document(services, loaded.document)
    assert copied.document.archive_version == 5
    assert copied.document.file_id != loaded.document.file_id
    assert copied.document.commands == loaded.document.commands
    path = tmp_path / "part.my3d"
    save_document(copied.document, path, reference_locations={})
    isolated = app.fork_app_services(services)
    reopened = app.open_app_document(isolated, path)
    assert isolated.kernel.execution_contexts[0].instance_id == identity
    reopened.bus.execute("feature.cylinder", {"radius": 2, "height": 8})
    assert tuple(c.instance_id for c in isolated.kernel.execution_contexts) == tuple(
        c.instance_id for c in reopened.document.commands
    )


def test_preview_preserves_old_ids_without_mutating_main_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 4})
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    before = document_payload(loaded.document)
    identity = loaded.document.commands[0].instance_id
    observed: list[ExecutionContext] = []
    original = BuildKernel.apply_with_context

    def record(
        self: BuildKernel, cid: str, params: Mapping[str, object], context: ExecutionContext
    ) -> None:
        observed.append(context)
        original(self, cid, params, context)

    monkeypatch.setattr(BuildKernel, "apply_with_context", record)
    app.preview_command(
        services, loaded.document.commands, "feature.cylinder", {"radius": 2, "height": 8}
    )
    assert observed[0].instance_id == identity
    assert observed[1].instance_id is not None and observed[1].instance_id != identity
    assert document_payload(loaded.document) == before


def test_empty_upgraded_document_preview_keeps_v5_context(monkeypatch: pytest.MonkeyPatch) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    observed: list[ExecutionContext] = []
    original = BuildKernel.apply_with_context

    def record(
        self: BuildKernel, cid: str, params: Mapping[str, object], context: ExecutionContext
    ) -> None:
        observed.append(context)
        original(self, cid, params, context)

    monkeypatch.setattr(BuildKernel, "apply_with_context", record)
    app.preview_command(
        services,
        (),
        "feature.box",
        {"size_x": 2, "size_y": 3, "size_z": 4},
        source_archive_version=loaded.document.archive_version,
    )
    assert observed[0].instance_id is not None
    assert loaded.document.commands == ()


def test_v5_snapshot_requires_explicit_host_upgrade_and_remains_exact(tmp_path: Path) -> None:
    from mycad.core.document import Document

    source_services = app.build_app(discoverers=[])
    source = app.new_workspace_document(source_services, kind="part")
    source.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 4})
    source.bus.apply_identity_upgrade(source.bus.prepare_identity_upgrade())
    params = app.reference_parameters(source.document)
    services = app.fork_app_services(source_services)
    legacy = Document(
        services.registry, archive_version=4, document_type="drawing2d", document_kind="drawing"
    )
    legacy_path = tmp_path / "legacy.my2d"
    save_document(legacy, legacy_path)
    host = app.open_app_document(services, legacy_path)
    with pytest.raises(ValidationError):
        host.bus.execute("reference.attach", params)
    assert host.document.commands == ()
    host.bus.apply_identity_upgrade(host.bus.prepare_identity_upgrade())
    host.bus.execute("reference.attach", params)
    assert services.kernel.document_references[0].archive == params["archive"]
    assert services.kernel.document_references[0].fingerprint == params["fingerprint"]
    path = tmp_path / "drawing.my2d"
    save_document(host.document, path)
    isolated = app.fork_app_services(services)
    app.open_app_document(isolated, path)
    assert isolated.kernel.document_references[0].archive == params["archive"]


def test_sketch_consumer_regeneration_reuses_contexts(monkeypatch: pytest.MonkeyPatch) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle_id, sketch_id = uuid4().hex, uuid4().hex
    radius = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle_id, "geometry"),), 5.0, "mm"
    )
    sketch = Sketch(
        sketch_id, WorkPlaneFrame.xy(), (CircleEntity(circle_id, (0, 0), 5),), (radius,)
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3))
    loaded.bus.execute(
        "feature.extrude", {"profile": {"type": "sketch", "sketch_id": sketch_id}, "distance": 4}
    )
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    before = loaded.document.commands
    current = services.kernel.sketches[0]
    revised = replace(radius, value=7.0)
    proposal = services.kernel.preview_sketch_constraint_update(current, revised)
    assert proposal.status == "success", proposal.message
    observed: list[ExecutionContext] = []
    original = BuildKernel.apply_with_context

    def record(
        self: BuildKernel, cid: str, params: Mapping[str, object], context: ExecutionContext
    ) -> None:
        observed.append(context)
        original(self, cid, params, context)

    monkeypatch.setattr(BuildKernel, "apply_with_context", record)
    loaded.bus.execute("sketch.constraint.update", proposal.command_params(current, revised))
    assert any(
        c.instance_id == before[1].instance_id and c.command_version == before[1].version
        for c in observed
    )
    assert tuple(c.instance_id for c in services.kernel.execution_contexts) == tuple(
        c.instance_id for c in loaded.document.commands
    )
    assert services.kernel.mass_properties().volume == pytest.approx(49 * pi * 4)


def test_v5_reference_update_reuses_host_contexts_and_undo() -> None:
    from tests.geom.test_document_reference_replay import source_sketch

    source_services = app.build_app(discoverers=[])
    source = source_sketch(source_services)
    source.bus.apply_identity_upgrade(source.bus.prepare_identity_upgrade())
    services = app.fork_app_services(source_services)
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    sketch = source_services.kernel.sketches[0]
    params = app.reference_parameters(source.document, object_id=sketch.sketch_id)
    loaded.bus.execute("reference.attach", params)
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": params["reference_id"]}, "distance": 4},
    )
    before = loaded.document.commands
    revised = Sketch(
        sketch.sketch_id, sketch.frame, (CircleEntity(sketch.entities[0].entity_id, (0, 0), 7),)
    )
    source.bus.edit_and_replay(0, revised.to_mapping(version=3), "local", "resize")
    updated = app.reference_parameters(
        source.document, object_id=sketch.sketch_id, reference_id=str(params["reference_id"])
    )
    loaded.bus.execute("reference.update", updated)
    assert tuple(c.instance_id for c in services.kernel.execution_contexts) == tuple(
        c.instance_id for c in loaded.document.commands
    )
    assert loaded.document.commands[:-1] == before
    assert services.kernel.mass_properties().volume == pytest.approx(49 * pi * 4)
    loaded.bus.undo()
    assert tuple(c.instance_id for c in services.kernel.execution_contexts) == tuple(
        c.instance_id for c in before
    )
    assert services.kernel.mass_properties().volume == pytest.approx(25 * pi * 4)
