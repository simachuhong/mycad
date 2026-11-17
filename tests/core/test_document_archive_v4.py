# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Persistent document identity and independent geometry ownership."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mycad import app
from mycad.core.document_kinds import DocumentKind
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document


@pytest.mark.parametrize(
    "kind,suffix", [("sketch", ".my2d"), ("drawing", ".my2d"), ("part", ".my3d")]
)
def test_workspace_document_identity_roundtrip(
    kind: DocumentKind, suffix: str, tmp_path: Path
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind=kind)
    target = tmp_path / f"document{suffix}"
    save_document(loaded.document, target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["version"] == (4 if kind == "part" else 8)
    assert payload["document_kind"] == kind
    assert payload["file_id"] == loaded.document.file_id
    reopened = app.open_app_document(services, target)
    assert reopened.document.document_kind == kind
    assert reopened.document.file_id == loaded.document.file_id
    assert reopened.document.document_id != loaded.document.document_id


def test_independent_services_do_not_reset_another_document() -> None:
    first = app.build_app(discoverers=[])
    a = app.new_workspace_document(first, kind="part")
    a.bus.execute("feature.box", {"size_x": 2.0, "size_y": 3.0, "size_z": 4.0}, "test")
    second = app.fork_app_services(first)
    b = app.new_workspace_document(second, kind="part")
    assert b.document.commands == ()
    assert second.kernel.body_ids == ()
    assert len(first.kernel.body_ids) == 1
    assert second.registry is first.registry


def test_v4_wrong_native_suffix_is_rejected(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    with pytest.raises(ValidationError, match="suffix"):
        save_document(loaded.document, tmp_path / "wrong.my2d")


def test_v4_rejects_inconsistent_kind_before_replay(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    target = tmp_path / "part.my3d"
    save_document(loaded.document, target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["document_kind"] = "drawing"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="kind"):
        app.open_app_document(services, target)


def test_open_rejects_misnamed_native_and_reserved_assembly_files(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    target = tmp_path / "part.my3d"
    save_document(loaded.document, target)
    for suffix in (".my2d", ".masm"):
        wrong = tmp_path / f"wrong{suffix}"
        wrong.write_bytes(target.read_bytes())
        with pytest.raises(ValidationError):
            app.open_app_document(services, wrong)


def test_reference_status_reports_missing_and_wrong_identity_sources(tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    source.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    target_services = app.fork_app_services(services)
    target = app.new_workspace_document(target_services, kind="part")
    target.bus.execute(
        "reference.attach",
        app.reference_parameters(source.document, object_id=sketch.sketch_id, path="source.my2d"),
        "local",
    )
    target_path = tmp_path / "part.my3d"
    save_document(target.document, target_path)
    opened = app.open_session_bundle(services, target_path)
    assert "缺失" in " ".join(opened.reference_messages)
    wrong = app.new_workspace_document(app.fork_app_services(services), kind="sketch")
    save_document(wrong.document, tmp_path / "source.my2d")
    opened = app.open_session_bundle(services, target_path)
    assert "身份不匹配" in " ".join(opened.reference_messages)
    save_document(source.document, tmp_path / "source.my2d")
    opened = app.open_session_bundle(services, target_path)
    assert "关联有效" in " ".join(opened.reference_messages)
