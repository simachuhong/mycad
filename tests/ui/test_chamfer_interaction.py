# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""End-to-end checks for preview-confirm chamfer interaction."""

from __future__ import annotations

from typing import cast

import pytest
from PySide6.QtWidgets import QDoubleSpinBox, QPushButton
from pytestqt.qtbot import QtBot

from mycad import app as mycad_app
from mycad.app import AppServices, build_app
from mycad.ui.main_window import MainWindow


def test_chamfer_picks_one_edge_previews_and_commits_only_on_confirmation(
    qtbot: QtBot,
) -> None:
    services: AppServices = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute(
        "feature.box",
        {
            "size_x": 20.0,
            "size_y": 20.0,
            "size_z": 10.0,
            "center": [0.0, 0.0, 0.0],
        },
        "test",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    viewport = window.viewport
    assert viewport is not None and window.command_palette is not None
    viewport.resize(900, 600)
    viewport.set_orientation("top")
    viewport.fit_view()

    window.command_palette.command_activated.emit("modify.chamfer")

    bar = window.modeling_command_bar
    assert bar is not None and bar.isVisible()
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert commit is not None
    assert viewport.selection_filter() == "edge"
    assert not commit.isEnabled()

    snapshot = viewport.snapshots()[-1]
    selected_lengths: list[float] = []
    first_midpoint: tuple[float, float, float] | None = None
    for edge in snapshot.boundary_edges:
        start, end = edge.points[:2]
        midpoint = (
            (start[0] + end[0]) / 2.0,
            (start[1] + end[1]) / 2.0,
            (start[2] + end[2]) / 2.0,
        )
        if first_midpoint is not None:
            separation = (
                sum((a - b) ** 2 for a, b in zip(midpoint, first_midpoint, strict=True)) ** 0.5
            )
            if separation < 19.0:
                continue
        projected = viewport.project_world_point(midpoint)
        if projected is None:
            continue
        target = viewport.selection_target_at(*projected, "edge")
        if target is None or edge.topology_id not in target.topology_ids:
            continue
        if not viewport.pick_at(*projected, toggle=True):
            continue
        if first_midpoint is None:
            first_midpoint = midpoint
        selected_lengths.append(sum((b - a) ** 2 for a, b in zip(start, end, strict=True)) ** 0.5)
        if len(selected_lengths) == 2:
            break
    assert len(selected_lengths) == 2
    selected = viewport.selection()
    assert selected is not None and len(selected.topology_ids) == 2

    original_volume = services.kernel.mass_properties().volume
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(original_volume)

    distance = bar.findChild(QDoubleSpinBox, "distance")
    assert distance is not None
    distance.setValue(999.0)
    qtbot.waitUntil(lambda: "预览失败" in window.status_command.text(), timeout=30000)
    assert not commit.isEnabled()
    assert len(loaded.document.commands) == 1
    distance.setValue(1.0)
    qtbot.waitUntil(commit.isEnabled, timeout=30000)

    commit.click()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)
    chamfer = loaded.document.commands[-1]
    assert chamfer.id == "modify.chamfer"
    assert chamfer.version == 1
    assert chamfer.params["distance"] == pytest.approx(1.0)
    edge_parameters = chamfer.params["edges"]
    assert isinstance(edge_parameters, list)
    assert len(cast("list[object]", edge_parameters)) == 2
    expected_volume = original_volume - sum(selected_lengths) / 2.0
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, abs=1e-6)
    assert "已完成建模操作" in window.status_command.text()
