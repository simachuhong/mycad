# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Version-six migration remains an isolated, auditable candidate transaction."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from mycad import app
from mycad.core.command_identity import ExecutionContext
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import document_payload, save_document
from mycad.core.replay_proposal import ReplayChangeSet


def test_v4_to_v6_candidate_cancel_and_commit_preserve_redo_and_audit(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    loaded.bus.execute("feature.cylinder", {"radius": 2, "height": 3})
    loaded.bus.undo()
    original = document_payload(loaded.document)
    old_command = loaded.document.commands[0]

    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=1
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded"
    assert preview.proposal.archive_version == 6
    assert preview.proposal.identity_upgrade is not None
    assert loaded.document.archive_version == 4
    assert document_payload(loaded.document) == original
    candidate.cancel()
    assert document_payload(loaded.document) == original

    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=1
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded"
    grant = candidate.authorize_commit(current_session_identity=1)
    candidate.commit(grant, current_session_identity=1)
    assert loaded.document.archive_version == 6
    command = loaded.document.commands[0]
    assert command.instance_id == preview.proposal.commands[0].instance_id
    assert command.timestamp_utc == old_command.timestamp_utc
    assert command.confirmed_by == old_command.confirmed_by
    loaded.bus.redo()
    assert loaded.document.commands[-1].instance_id is not None
    path = tmp_path / "spatial.my3d"
    save_document(loaded.document, path)
    reopened_services = app.fork_app_services(services)
    reopened = app.open_app_document(reopened_services, path)
    assert reopened.document.archive_version == 6
    assert reopened.document.commands == loaded.document.commands
    assert reopened_services.kernel.mass_properties().volume == pytest.approx(
        12 * 3.141592653589793
    )


def test_v6_candidate_rejects_invalid_target_and_source_change() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=2)
    with pytest.raises(ValidationError):
        candidate.stage(
            ReplayChangeSet((), (), False, target_archive_version=7), current_session_identity=2
        )
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=2
    )
    loaded.bus.execute("feature.box", {"size_x": 1, "size_y": 1, "size_z": 1})
    assert candidate.preview(current_session_identity=2).state == "stale"


def test_v5_to_v6_does_not_reassign_existing_identities() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    loaded.bus.execute("feature.box", {"size_x": 4, "size_y": 5, "size_z": 6})
    old = loaded.document.commands
    candidate = app.create_replay_candidate(services, loaded, session_identity=4)
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=4
    )
    preview = candidate.preview(current_session_identity=4)
    assert preview.state == "succeeded"
    assert preview.proposal.identity_upgrade is None
    candidate.commit(
        candidate.authorize_commit(current_session_identity=4), current_session_identity=4
    )
    assert loaded.document.archive_version == 6
    assert loaded.document.commands == old


def test_v6_commit_failure_restores_source_and_redo(monkeypatch: pytest.MonkeyPatch) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    loaded.bus.execute("feature.cylinder", {"radius": 2, "height": 3})
    loaded.bus.undo()
    loaded.document.mark_clean()
    before = document_payload(loaded.document)
    candidate = app.create_replay_candidate(services, loaded, session_identity=5)
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=5
    )
    assert candidate.preview(current_session_identity=5).state == "succeeded"
    grant = candidate.authorize_commit(current_session_identity=5)
    original_apply = services.kernel.apply_with_context
    failed = False

    def fail_once(command_id: str, params: Mapping[str, object], context: ExecutionContext) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise ValidationError("injected commit fault")
        original_apply(command_id, params, context)

    monkeypatch.setattr(services.kernel, "apply_with_context", fail_once)
    with pytest.raises(ValidationError):
        candidate.commit(grant, current_session_identity=5)
    assert document_payload(loaded.document) == before
    assert loaded.document.archive_version == 4
    assert not loaded.document.is_dirty
    assert services.kernel.mass_properties().volume == pytest.approx(400)
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(12 * 3.141592653589793)


def test_nested_v6_reference_requires_a_v6_container() -> None:
    from copy import deepcopy
    from uuid import uuid4

    from mycad.core.document_references import archive_fingerprint
    from mycad.core.schema_v5 import validate_archive_v5
    from mycad.core.schema_v6 import validate_archive_v6
    from tests.core.test_document_references import archive

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=6)
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=6
    )
    assert candidate.preview(current_session_identity=6).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=6), current_session_identity=6
    )
    source = document_payload(loaded.document)
    host = archive(uuid4().hex)
    host.update(version=6, document_kind="drawing", document_type="drawing2d")
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
                "fingerprint": archive_fingerprint(source),
            },
        }
    ]
    validate_archive_v6(host)
    old_host = deepcopy(host)
    old_host["version"] = 5
    with pytest.raises(ValidationError):
        validate_archive_v5(old_host)


def test_v6_save_as_preserves_ids_and_redo(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=7)
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=7
    )
    assert candidate.preview(current_session_identity=7).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=7), current_session_identity=7
    )
    loaded.bus.execute("feature.box", {"size_x": 3, "size_y": 4, "size_z": 5})
    loaded.bus.execute("feature.cylinder", {"radius": 2, "height": 3})
    undo_id = loaded.document.commands[-1].instance_id
    loaded.bus.undo()
    _, copied = app.copy_app_document(services, loaded.document, source_bus=loaded.bus)
    assert copied.document.file_id != loaded.document.file_id
    assert copied.document.archive_version == 6
    assert copied.document.commands == loaded.document.commands
    path = tmp_path / "copied.my3d"
    save_document(copied.document, path)
    copied.bus.redo()
    assert copied.document.commands[-1].instance_id == undo_id
    assert services.kernel.mass_properties().volume == pytest.approx(12 * 3.141592653589793)


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "noncanonical"])
def test_v6_rejects_invalid_identity_before_opening(corruption: str, tmp_path: Path) -> None:
    import json
    from typing import cast

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=11)
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=11
    )
    assert candidate.preview(current_session_identity=11).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=11), current_session_identity=11
    )
    loaded.bus.execute("feature.box", {"size_x": 3, "size_y": 4, "size_z": 5})
    loaded.bus.execute("feature.cylinder", {"radius": 2, "height": 3})
    payload = document_payload(loaded.document)
    commands = cast("list[dict[str, object]]", payload["commands"])
    if corruption == "missing":
        del commands[1]["instance_id"]
    elif corruption == "duplicate":
        commands[1]["instance_id"] = commands[0]["instance_id"]
    else:
        commands[1]["instance_id"] = "A" * 32
    path = tmp_path / "invalid.my3d"
    path.write_text(json.dumps(payload), encoding="utf-8")
    volume = services.kernel.mass_properties().volume
    with pytest.raises(ValidationError):
        app.open_app_document(services, path)
    assert services.kernel.mass_properties().volume == pytest.approx(volume)
    assert len(loaded.document.commands) == 2
