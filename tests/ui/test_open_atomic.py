# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Opening an invalid archive must leave the active UI session intact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from PySide6.QtWidgets import QFileDialog

from mycad.app import build_app, new_document
from mycad.core.persistence import save_document
from mycad.ui.main_window import MainWindow
from tests.helpers.step_roundtrip import read_step

if TYPE_CHECKING:
    from pytest import MonkeyPatch
    from pytestqt.qtbot import QtBot

    from mycad.app import AppServices


pytestmark = pytest.mark.usefixtures("choose_new_part")


@pytest.fixture
def services() -> AppServices:
    return build_app(discoverers=[])


def _write_late_invalid_archive(path: Path) -> None:
    """Create a two-command archive whose second command cannot be replayed."""
    source = build_app(discoverers=[])
    candidate = new_document(source)
    for size_x in (20.0, 30.0):
        candidate.bus.execute(
            "feature.box",
            {"size_x": size_x, "size_y": 10.0, "size_z": 10.0},
        )
    save_document(candidate.document, path)

    archive = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    commands = cast("list[object]", archive["commands"])
    second = cast("dict[str, object]", commands[1])
    params = cast("dict[str, object]", second["params"])
    params["size_x"] = -1.0
    path.write_text(json.dumps(archive), encoding="utf-8")


def _window(services: AppServices, qtbot: QtBot) -> MainWindow:
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    return window


def test_file_open_runs_on_worker_and_rebinds_after_completion(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    source = new_document(services)
    source.bus.execute(
        "feature.box",
        {"size_x": 8.0, "size_y": 8.0, "size_z": 8.0},
        "test",
    )
    target = tmp_path / "worker-open.mc.json"
    save_document(source.document, target)

    window = _window(services, qtbot)
    window.act_new.triggered.emit()
    before = window.loaded_document()
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "")),
    )
    window.act_open.triggered.emit()

    assert window.execution_unit is not None
    assert window.execution_unit.is_busy
    qtbot.waitUntil(lambda: window.loaded_document() is not before)
    loaded = window.loaded_document()
    assert loaded is not None
    assert loaded.document.commands[0].params["size_x"] == 8.0


def test_failed_open_preserves_active_session_and_exports(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    original_path = tmp_path / "active.mc.json"
    bad_path = tmp_path / "bad.mc.json"
    export_path = tmp_path / "active.step"
    _write_late_invalid_archive(bad_path)

    window = _window(services, qtbot)
    window.act_new.triggered.emit()
    active = window.loaded_document()
    assert active is not None
    active.bus.execute(
        "feature.box",
        {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0},
    )

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(original_path), "")),
    )
    window.act_save_as.triggered.emit()
    active.bus.execute("feature.cylinder", {"radius": 1.0, "height": 2.0})
    window.request_undo()
    qtbot.waitUntil(lambda: len(active.document.commands) == 1)
    undo_unit = window.execution_unit
    assert undo_unit is not None
    qtbot.waitUntil(lambda: not undo_unit.is_busy)
    assert active.document.is_dirty
    assert services.kernel.mass_properties().volume == pytest.approx(1000.0)

    errors: list[str] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(bad_path), "")),
    )
    monkeypatch.setattr(window, "_show_error", errors.append)
    window.act_open.triggered.emit()
    qtbot.waitUntil(lambda: bool(errors))

    assert window.loaded_document() is active
    assert window.viewport is not None
    assert active.document.is_dirty
    assert len(active.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(1000.0)

    alternate_path = tmp_path / "unexpected-save-as.mc.json"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(alternate_path), "")),
    )
    window.act_save.triggered.emit()
    assert not alternate_path.exists()
    saved = cast("dict[str, object]", json.loads(original_path.read_text(encoding="utf-8")))
    saved_commands = cast("list[object]", saved["commands"])
    assert len(saved_commands) == 1
    assert cast("dict[str, object]", saved_commands[0])["id"] == "feature.box"

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(export_path), "")),
    )
    window.act_export.triggered.emit()
    solids, volume = read_step(export_path)
    assert solids == 1
    assert volume == pytest.approx(1000.0, abs=1e-6)

    window.request_redo()
    qtbot.waitUntil(lambda: len(active.document.commands) == 2)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert len(active.document.commands) == 2
    assert services.kernel.mass_properties().volume == pytest.approx(2.0 * 3.141592653589793)
