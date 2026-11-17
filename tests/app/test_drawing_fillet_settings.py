# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drawing fillet defaults are replayed with the document."""

import json
from pathlib import Path

import pytest

from mycad import app
from mycad.core.document import Document
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet


def test_fillet_radius_document_replays_and_reopens(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    assert services.kernel.drawing_fillet_radius == 0
    loaded.bus.execute("drawing.fillet_radius.set", {"radius": 4.5}, "local", version=1)
    assert services.kernel.drawing_fillet_radius == pytest.approx(4.5)
    path = tmp_path / "fillet-settings.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_fillet_radius == pytest.approx(4.5)
    reopened.bus.undo()
    assert services.kernel.drawing_fillet_radius == 0
    reopened.bus.redo()
    assert services.kernel.drawing_fillet_radius == pytest.approx(4.5)


def test_setting_radius_avoids_history_copies_for_ordinals(monkeypatch: pytest.MonkeyPatch) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    original = Document.commands.fget
    assert original is not None
    snapshots = 0

    def count_snapshots(document: Document) -> tuple[object, ...]:
        nonlocal snapshots
        snapshots += 1
        return original(document)

    monkeypatch.setattr(Document, "commands", property(count_snapshots))
    loaded.bus.execute("drawing.fillet_radius.set", {"radius": 2}, "local", version=1)
    assert snapshots == 2


@pytest.mark.parametrize("candidate", [False, True])
def test_fillet_radius_is_rejected_in_part_document(candidate: bool) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services)
    with pytest.raises(ValidationError, match="二维"):
        if candidate:
            loaded.bus.prepare_replay_proposal(
                ReplayChangeSet(
                    (),
                    (ReplayAppend("drawing.fillet_radius.set", 1, {"radius": 2}, "local"),),
                    False,
                ),
                session_identity=0,
                candidate_id="fillet-radius-part",
                generation=0,
            )
        else:
            loaded.bus.execute("drawing.fillet_radius.set", {"radius": 2}, "local", version=1)
    assert not loaded.document.commands
    assert services.kernel.drawing_fillet_radius == 1


def test_fillet_radius_candidate_accepts_drawing_document() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    proposal = loaded.bus.prepare_replay_proposal(
        ReplayChangeSet(
            (), (ReplayAppend("drawing.fillet_radius.set", 1, {"radius": 2}, "local"),), False
        ),
        session_identity=0,
        candidate_id="fillet-radius-drawing",
        generation=0,
    )
    assert proposal.commands[-1].id == "drawing.fillet_radius.set"
    assert not loaded.document.commands


def test_previously_written_part_radius_command_replays(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    loaded.bus.execute("drawing.fillet_radius.set", {"radius": 2}, "local", version=1)
    path = tmp_path / "legacy-part.mc.json"
    save_document(loaded.document, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["document_type"] = "part"
    payload["version"] = 3
    for key in ("document_kind", "file_id", "reference_locations", "drawing_defaults"):
        payload.pop(key, None)
    for command in payload["commands"]:
        command.pop("instance_id", None)
    path.write_text(json.dumps(payload), encoding="utf-8")
    reopened = app.open_app_document(services, path)
    assert reopened.document.document_type == "part"
    assert services.kernel.drawing_fillet_radius == 2
    reopened.bus.undo()
    assert services.kernel.drawing_fillet_radius == 1
    reopened.bus.redo()
    assert services.kernel.drawing_fillet_radius == 2


@pytest.mark.parametrize("radius", [-1.0, float("nan"), float("inf"), True])
def test_invalid_fillet_radius_keeps_history_and_state(radius: object) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.fillet_radius.set", {"radius": radius}, "local", version=1)
    assert services.kernel.drawing_fillet_radius == 0
    assert not loaded.document.commands
