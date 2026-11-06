# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The application composition root stages archive replay off-session."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from mycad.app import build_app, new_document, open_app_document
from mycad.core.command_identity import ExecutionContext
from mycad.core.exceptions import GeometryBuildError, MycadError
from mycad.core.persistence import save_document
from mycad.geom.kernel import BuildKernel

if TYPE_CHECKING:
    from pytest import MonkeyPatch

    from mycad.app import AppServices
    from mycad.core.persistence import LoadedDocument


def _active_model(services: AppServices) -> LoadedDocument:
    active = new_document(services)
    active.bus.execute("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    active.bus.execute("feature.cylinder", {"radius": 1.0, "height": 2.0})
    active.bus.undo()
    return active


def _write_archive(path: Path, failure: str | None) -> None:
    source = build_app(discoverers=[])
    candidate = new_document(source)
    for size_x in (20.0, 30.0):
        candidate.bus.execute(
            "feature.box",
            {"size_x": size_x, "size_y": 10.0, "size_z": 10.0},
        )
    save_document(candidate.document, path)
    if failure == "malformed-json":
        path.write_text("{not json", encoding="utf-8")
        return

    archive = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    if failure == "unknown-version":
        archive["version"] = 99
    elif failure == "unknown-command":
        commands = cast("list[object]", archive["commands"])
        cast("dict[str, object]", commands[1])["id"] = "feature.unknown"
    elif failure == "invalid-later-params":
        commands = cast("list[object]", archive["commands"])
        second = cast("dict[str, object]", commands[1])
        cast("dict[str, object]", second["params"])["size_x"] = -1.0
    path.write_text(json.dumps(archive), encoding="utf-8")


@pytest.fixture
def services() -> AppServices:
    return build_app(discoverers=[])


@pytest.mark.parametrize(
    "failure",
    ["malformed-json", "unknown-version", "unknown-command", "invalid-later-params"],
)
def test_archive_failures_preserve_active_state(
    services: AppServices, tmp_path: Path, failure: str
) -> None:
    path = tmp_path / f"{failure}.mc.json"
    _write_archive(path, failure)
    active = _active_model(services)

    with pytest.raises(MycadError):
        open_app_document(services, path)

    assert services.kernel.mass_properties().volume == pytest.approx(1000.0)
    assert active.document.is_dirty
    assert len(active.document.commands) == 1
    active.bus.redo()
    assert len(active.document.commands) == 2
    assert services.kernel.mass_properties().volume == pytest.approx(2.0 * 3.141592653589793)


def test_geometry_rebuild_failure_preserves_active_state(
    services: AppServices,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    path = tmp_path / "geometry-failure.mc.json"
    _write_archive(path, None)
    active = _active_model(services)
    original_apply = BuildKernel.apply_with_context
    replay_count = 0

    def fail_second_candidate_apply(
        kernel: BuildKernel,
        command_id: str,
        params: Mapping[str, object],
        context: ExecutionContext,
    ) -> None:
        nonlocal replay_count
        if kernel is not services.kernel:
            replay_count += 1
            if replay_count == 2:
                raise GeometryBuildError("candidate geometry failure")
        original_apply(kernel, command_id, params, context)

    monkeypatch.setattr(BuildKernel, "apply_with_context", fail_second_candidate_apply)

    with pytest.raises(GeometryBuildError, match="candidate geometry failure"):
        open_app_document(services, path)

    assert replay_count == 2
    assert active.document.is_dirty
    assert len(active.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(1000.0)


def test_viewport_mesh_cache_tracks_undo_redo_and_open(
    services: AppServices, tmp_path: Path
) -> None:
    active = new_document(services)
    active.bus.execute("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    first_mesh = services.kernel.viewport_data()[0].mesh
    active.bus.execute("feature.box", {"size_x": 20.0, "size_y": 20.0, "size_z": 20.0})
    second_mesh = services.kernel.viewport_data()[0].mesh
    assert second_mesh != first_mesh

    active.bus.undo()
    assert services.kernel.viewport_data()[0].mesh == first_mesh
    active.bus.redo()
    assert services.kernel.viewport_data()[0].mesh == second_mesh

    path = tmp_path / "replacement.mc.json"
    _write_archive(path, None)
    opened = open_app_document(services, path)
    opened_mesh = services.kernel.viewport_data()[0].mesh
    assert opened.document.commands[-1].params["size_x"] == 30.0
    assert opened_mesh != second_mesh
    assert services.kernel.viewport_data()[0].mesh == opened_mesh
