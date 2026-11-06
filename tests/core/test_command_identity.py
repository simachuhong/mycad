# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Versioned command identities are adopted only by explicit Bus transactions."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from mycad.commands.demo import demo_registry
from mycad.core.bus import CommandBus
from mycad.core.document import Document
from mycad.core.exceptions import GeometryBuildError, ValidationError
from mycad.core.handlers import BuiltinModelingHandler
from mycad.core.persistence import document_payload, load_document_payload, save_document
from tests.core.test_persistence import FakeKernel


def make_bus() -> tuple[Document, CommandBus, FakeKernel]:
    registry = demo_registry()
    document = Document(registry)
    kernel = FakeKernel()
    bus = CommandBus(
        document, registry, kernel, {"feature.cylinder": BuiltinModelingHandler("feature.cylinder")}
    )
    return document, bus, kernel


def test_upgrade_adopts_exact_proposal_and_preserves_redo_audit() -> None:
    doc, bus, _kernel = make_bus()
    bus.execute("feature.cylinder", {"radius": 4, "height": 2}, "local")
    bus.execute("feature.cylinder", {"radius": 5, "height": 2}, "local")
    original = doc.commands
    bus.undo()
    proposal = bus.prepare_identity_upgrade()
    assert doc.archive_version == 1
    assert doc.commands[0].instance_id is None
    bus.apply_identity_upgrade(proposal)
    assert doc.archive_version == 5
    assert doc.commands[0].instance_id == proposal.active_ids[0]
    bus.redo()
    assert doc.commands[1].instance_id == proposal.redo_ids[0]
    assert [c.timestamp_utc for c in doc.commands] == [c.timestamp_utc for c in original]
    identity = doc.commands[0].instance_id
    bus.edit_and_replay(0, {"radius": 6, "height": 2}, "local", "resize")
    assert doc.commands[0].instance_id == identity
    assert doc.commands[0].timestamp_utc == original[0].timestamp_utc
    assert len(doc.commands[0].amendments) == 1


def test_stale_or_tampered_proposal_does_not_upgrade() -> None:
    doc, bus, _kernel = make_bus()
    proposal = bus.prepare_identity_upgrade()
    with pytest.raises(ValidationError):
        bus.apply_identity_upgrade(replace(proposal, active_ids=("a" * 32,)))
    bus.execute("feature.cylinder", {"radius": 4, "height": 2})
    before = document_payload(doc)
    with pytest.raises(ValidationError):
        bus.apply_identity_upgrade(proposal)
    assert document_payload(doc) == before
    assert doc.archive_version == 1


def test_failed_upgrade_restores_legacy_format_dirty_and_redo() -> None:
    doc, bus, kernel = make_bus()
    bus.execute("feature.cylinder", {"radius": 4, "height": 2})
    bus.execute("feature.cylinder", {"radius": 5, "height": 2})
    bus.undo()
    doc.mark_clean()
    before = document_payload(doc)
    proposal = bus.prepare_identity_upgrade()
    failed = False

    def fail_once(_n: int, _cid: str, _params: dict[str, object]) -> Exception | None:
        nonlocal failed
        if not failed:
            failed = True
            return GeometryBuildError("injected")
        return None

    kernel.fail_when = fail_once
    with pytest.raises(GeometryBuildError):
        bus.apply_identity_upgrade(proposal)
    assert document_payload(doc) == before
    assert not doc.is_dirty
    bus.redo()
    assert len(doc.commands) == 2
    assert all(command.instance_id is None for command in doc.commands)


def test_v5_save_open_retains_ids_and_legacy_wire_is_unchanged(tmp_path: Path) -> None:
    doc, bus, _kernel = make_bus()
    bus.execute("feature.cylinder", {"radius": 4, "height": 2})
    legacy = document_payload(doc)
    assert "instance_id" not in cast("list[dict[str, object]]", legacy["commands"])[0]
    bus.apply_identity_upgrade(bus.prepare_identity_upgrade())
    path = tmp_path / "part.my3d"
    save_document(doc, path)
    payload = document_payload(doc)
    loaded = load_document_payload(
        payload,
        registry=demo_registry(),
        kernel=FakeKernel(),
        handlers={"feature.cylinder": BuiltinModelingHandler("feature.cylinder")},
    )
    assert loaded.document.commands == doc.commands
    bus.undo()
    assert doc.archive_version == 5
    bus.redo()
    assert doc.commands == loaded.document.commands


@pytest.mark.parametrize("bad_id", [None, "not-a-uuid", "A" * 32])
def test_v5_rejects_missing_or_noncanonical_id(bad_id: object) -> None:
    doc, bus, _kernel = make_bus()
    bus.execute("feature.cylinder", {"radius": 4, "height": 2})
    bus.apply_identity_upgrade(bus.prepare_identity_upgrade())
    payload = document_payload(doc)
    commands = cast("list[dict[str, object]]", payload["commands"])
    if bad_id is None:
        del commands[0]["instance_id"]
    else:
        commands[0]["instance_id"] = bad_id
    with pytest.raises(ValidationError):
        load_document_payload(payload, registry=demo_registry(), kernel=FakeKernel(), handlers={})


def test_new_v5_commands_and_redo_branch_have_distinct_ids() -> None:
    doc, bus, _kernel = make_bus()
    bus.apply_identity_upgrade(bus.prepare_identity_upgrade())
    bus.execute("feature.cylinder", {"radius": 4, "height": 2})
    old = doc.commands[0].instance_id
    bus.undo()
    bus.execute("feature.cylinder", {"radius": 4, "height": 2})
    assert doc.commands[0].instance_id != old


def test_duplicate_ids_and_new_fields_in_v4_are_rejected() -> None:
    doc, bus, _kernel = make_bus()
    bus.apply_identity_upgrade(bus.prepare_identity_upgrade())
    for radius in (4, 5):
        bus.execute("feature.cylinder", {"radius": radius, "height": 2})
    payload = document_payload(doc)
    commands = cast("list[dict[str, object]]", payload["commands"])
    commands[1]["instance_id"] = commands[0]["instance_id"]
    with pytest.raises(ValidationError, match="duplicate"):
        load_document_payload(payload, registry=demo_registry(), kernel=FakeKernel(), handlers={})
    payload = document_payload(doc)
    payload["version"] = 4
    with pytest.raises(ValidationError):
        load_document_payload(payload, registry=demo_registry(), kernel=FakeKernel(), handlers={})


def test_upgrade_proposal_cannot_be_used_in_another_document() -> None:
    _doc, bus, _kernel = make_bus()
    other, other_bus, _other_kernel = make_bus()
    with pytest.raises(ValidationError):
        other_bus.apply_identity_upgrade(bus.prepare_identity_upgrade())
    assert other.archive_version == 1


def test_failed_batch_restores_v5_ids_and_redo() -> None:
    from mycad.core.document import PlannedCommand
    from mycad.core.exceptions import BatchRollbackError
    from mycad.core.plan import Plan

    doc, bus, kernel = make_bus()
    bus.apply_identity_upgrade(bus.prepare_identity_upgrade())
    bus.execute("feature.cylinder", {"radius": 4, "height": 2})
    bus.execute("feature.cylinder", {"radius": 5, "height": 2})
    redo_id = doc.commands[-1].instance_id
    bus.undo()
    before = doc.commands
    plan = Plan(
        [
            PlannedCommand(
                "feature.cylinder", 1, {"radius": 6, "height": 2}, "create", "cylinder_body"
            ),
            PlannedCommand(
                "feature.cylinder", 1, {"radius": 7, "height": 2}, "create", "cylinder_body"
            ),
        ]
    )
    bus.confirm_plan(plan, "local", scope="cli")
    kernel.fail_when = lambda _n, _cid, p: (
        GeometryBuildError("injected") if p["radius"] == 7 else None
    )
    with pytest.raises(BatchRollbackError):
        bus.execute_batch(plan, scope="cli")
    assert doc.commands == before
    bus.redo()
    assert doc.commands[-1].instance_id == redo_id


def test_identity_only_document_replacement_preserves_redo() -> None:
    doc, bus, _kernel = make_bus()
    bus.apply_identity_upgrade(bus.prepare_identity_upgrade())
    for radius in (4, 5):
        bus.execute("feature.cylinder", {"radius": radius, "height": 2})
    identity = doc.commands[-1].instance_id
    bus.undo()
    replacement = Document(demo_registry(), commands=doc.commands, archive_version=5)
    copied_bus = bus.copy_for_document(replacement)
    copied_bus.redo()
    assert replacement.commands[-1].instance_id == identity
    assert len(doc.commands) == 1


@pytest.mark.parametrize("fault", ["identity", "fingerprint"])
def test_nested_v5_invalid_source_is_rejected_during_preflight(fault: str) -> None:
    from uuid import uuid4

    from mycad.core.document_references import archive_fingerprint
    from mycad.core.schema_v5 import validate_archive_v5
    from tests.core.test_document_references import archive

    doc, bus, _kernel = make_bus()
    bus.execute("feature.cylinder", {"radius": 4, "height": 2})
    bus.apply_identity_upgrade(bus.prepare_identity_upgrade())
    source = document_payload(doc)
    if fault == "identity":
        cast("list[dict[str, object]]", source["commands"])[0]["instance_id"] = "invalid"
    fingerprint = archive_fingerprint(source) if fault == "identity" else "wrong"
    host = archive(uuid4().hex)
    host.update(version=5, document_kind="drawing", document_type="drawing2d")
    host["commands"] = [
        {
            "id": "reference.attach",
            "version": 1,
            "ordinal": 0,
            "timestamp_utc": "original",
            "confirmed_by": None,
            "instance_id": uuid4().hex,
            "params": {
                "reference_id": uuid4().hex,
                "file_id": source["file_id"],
                "kind": "part",
                "path": "",
                "object_id": "",
                "archive": source,
                "fingerprint": fingerprint,
            },
        }
    ]
    with pytest.raises(ValidationError):
        validate_archive_v5(host)


def test_minimum_archive_version_checked_before_handler() -> None:
    from dataclasses import replace as changed

    from mycad.commands.demo import cylinder_spec
    from mycad.commands.registry import CommandRegistry

    registry = CommandRegistry(demo_registry().schema_defs)
    registry.register(changed(cylinder_spec(), min_archive_version=5))
    doc = Document(registry)
    kernel = FakeKernel()
    bus = CommandBus(
        doc, registry, kernel, {"feature.cylinder": BuiltinModelingHandler("feature.cylinder")}
    )
    with pytest.raises(ValidationError):
        bus.execute("feature.cylinder", {"radius": 4, "height": 2})
    assert kernel.applied == []


def test_invalid_legacy_upgrade_does_not_reset_unchanged_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycad.commands.demo import cylinder_spec
    from mycad.commands.registry import CommandRegistry

    registry = CommandRegistry(demo_registry().schema_defs)
    registry.register(replace(cylinder_spec(), id="drawing.note.create"))
    doc = Document(registry)
    kernel = FakeKernel()
    bus = CommandBus(
        doc,
        registry,
        kernel,
        {"drawing.note.create": BuiltinModelingHandler("drawing.note.create")},
    )
    bus.execute("drawing.note.create", {"radius": 4, "height": 2})
    before = doc.commands

    def forbidden_reset() -> None:
        pytest.fail("format validation failure must not reset untouched geometry")

    monkeypatch.setattr(kernel, "reset", forbidden_reset)
    with pytest.raises(ValidationError):
        bus.apply_identity_upgrade(bus.prepare_identity_upgrade())
    assert doc.commands == before
    assert doc.archive_version == 1
