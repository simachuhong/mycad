# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Sphere travels through the actual command and replay paths."""

import math
from pathlib import Path

import pytest

from mycad.app import build_app, new_workspace_document, open_app_document
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document


def test_sphere_bus_undo_and_redo() -> None:
    services = build_app(discoverers=[])
    loaded = new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.sphere", {"radius": 10, "center": [1, 2, 3]})
    assert services.kernel.mass_properties().volume == pytest.approx(4 * math.pi * 1000 / 3)
    loaded.bus.undo()
    assert services.kernel.mass_properties().solid_count == 0
    loaded.bus.redo()
    assert services.kernel.mass_properties().center_of_mass == pytest.approx((1, 2, 3))


def test_sphere_schema_rejects_extra_parameter() -> None:
    services = build_app(discoverers=[])
    loaded = new_workspace_document(services, kind="part")
    with pytest.raises(ValidationError):
        loaded.bus.execute("feature.sphere", {"radius": 1, "height": 2})
    assert not loaded.document.commands


def test_sphere_archive_round_trip_preserves_version_and_geometry(tmp_path: Path) -> None:
    services = build_app(discoverers=[])
    loaded = new_workspace_document(services, kind="part")
    version = loaded.document.archive_version
    loaded.bus.execute("feature.sphere", {"radius": 4, "center": [1, 2, 3]})
    path = tmp_path / "sphere.mc.json"
    save_document(loaded.document, path)
    reopened = open_app_document(services, path)
    assert reopened.document.archive_version == version
    assert reopened.document.commands[0].id == "feature.sphere"
    assert services.kernel.mass_properties().center_of_mass == pytest.approx((1, 2, 3))
    assert services.kernel.mass_properties().volume == pytest.approx(256 * math.pi / 3)


def test_sphere_with_identity_can_be_edited_and_replayed() -> None:
    services = build_app(discoverers=[])
    loaded = new_workspace_document(services, kind="part")
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    loaded.bus.execute("feature.sphere", {"radius": 3})
    identity = loaded.document.commands[0].instance_id
    assert identity is not None
    loaded.bus.edit_and_replay(0, {"radius": 5}, "local", "resize")
    assert loaded.document.commands[0].instance_id == identity
    assert services.kernel.mass_properties().volume == pytest.approx(500 * math.pi / 3)


def test_sphere_step_and_stl_exports(tmp_path: Path) -> None:
    from tests.helpers.step_roundtrip import read_step

    services = build_app(discoverers=[])
    loaded = new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.sphere", {"radius": 4})
    step_path = tmp_path / "sphere.step"
    stl_path = tmp_path / "sphere.stl"
    services.formats.resolve(step_path).write(services.kernel, step_path)
    services.formats.resolve(stl_path).write(services.kernel, stl_path)
    count, volume = read_step(step_path)
    assert count == 1
    assert volume == pytest.approx(256 * math.pi / 3)
    assert stl_path.stat().st_size > 84


def test_sphere_preview_and_failure_preserve_source_and_redo() -> None:
    from mycad.app import preview_command
    from mycad.core.persistence import document_payload

    services = build_app(discoverers=[])
    loaded = new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10})
    loaded.bus.execute("feature.sphere", {"radius": 3})
    loaded.bus.undo()
    loaded.document.mark_clean()
    payload = document_payload(loaded.document)
    revision = loaded.document.revision
    preview_command(services, loaded.document.commands, "feature.sphere", {"radius": 4})
    with pytest.raises(ValidationError):
        preview_command(services, loaded.document.commands, "feature.sphere", {"radius": -1})
    assert document_payload(loaded.document) == payload
    assert loaded.document.revision == revision
    assert not loaded.document.is_dirty
    assert services.kernel.mass_properties().volume == pytest.approx(1000)
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(36 * math.pi)
