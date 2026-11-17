# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Task-level bracket and generic array workflows through actual GUI controls."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFileDialog, QPushButton, QSpinBox, QWidget
from pytestqt.qtbot import QtBot

from mycad.app import AppServices, build_app
from mycad.ui.main_window import MainWindow
from mycad.ui.right_panel import HistoryEditDialog
from tests.helpers.step_roundtrip import read_step

pytestmark = pytest.mark.usefixtures("choose_new_part")


def _number(parent: QWidget, name: str, value: float) -> None:
    field = parent.findChild(QDoubleSpinBox, name)
    assert field is not None, name
    field.setValue(value)


def _choice(parent: QWidget, name: str, value: str) -> None:
    field = parent.findChild(QComboBox, name)
    assert field is not None, name
    index = field.findData(value)
    assert index >= 0, (name, value)
    field.setCurrentIndex(index)


def _start(window: MainWindow, command: str) -> QWidget:
    assert window.command_palette is not None and window.viewport is not None
    window.command_palette.command_activated.emit(command)
    window.viewport.set_orientation("top")
    window.viewport.fit_view()
    bar = window.modeling_command_bar
    assert bar is not None
    return bar


def _pick(window: MainWindow, point: tuple[float, float, float], *, toggle: bool = False) -> None:
    view = window.viewport
    assert view is not None
    screen = view.project_world_point(point)
    assert screen is not None and view.pick_at(*screen, toggle=toggle), point


def _confirm(qtbot: QtBot, window: MainWindow, button: QPushButton | None = None) -> None:
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    before = len(loaded.document.commands)
    if button is None:
        bar = window.modeling_command_bar
        assert bar is not None
        button = bar.findChild(QPushButton, "modelingCommitButton")
    assert button is not None
    qtbot.waitUntil(button.isEnabled, timeout=30000)
    assert len(loaded.document.commands) == before
    button.click()
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before + 1 and not unit.is_busy, timeout=30000
    )


def _archive(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    window: MainWindow,
    services: AppServices,
    path: Path,
    volume: float,
    count: int,
) -> None:
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    signature = tuple(
        (o.result, o.inputs) for o in services.kernel.viewport_data()[-1].body_origins
    )

    def archive_path(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", archive_path)
    window.act_save_as.trigger()
    assert path.exists()
    step = path.with_suffix(".step")

    def step_path(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(step), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", step_path)
    window.act_export.trigger()
    actual_count, actual_volume = read_step(step)
    assert actual_count == count
    assert actual_volume == pytest.approx(volume, rel=1e-7)
    assert window.viewport is not None
    QTest.keyClick(window.viewport, Qt.Key.Key_Escape)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", archive_path)
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.loaded_document() is not loaded and not unit.is_busy, timeout=30000
    )
    assert services.kernel.geometry_check().is_valid
    assert services.kernel.mass_properties().solid_count == count
    assert services.kernel.mass_properties().volume == pytest.approx(volume, rel=1e-7)
    assert (
        tuple((o.result, o.inputs) for o in services.kernel.viewport_data()[-1].body_origins)
        == signature
    )


@pytest.mark.parametrize("finish", ["fillet", "chamfer"])
def test_symmetric_bracket_from_gui_copy_mirror_union_and_two_edges(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    finish: str,
) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1500, 950)
    window.show()
    window.act_new.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.lock_plane()
    vertices = ((0, 0), (30, 0), (30, 30), (24, 30), (24, 6), (0, 6))
    for start, end in zip(vertices, (*vertices[1:], vertices[0]), strict=True):
        task.select_tool("line")
        task.place_uv(start)
        task.place_uv(end)
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 1 and not unit.is_busy, timeout=30000)
    bar = _start(window, "feature.extrude")
    _choice(bar, "extrudeSource", "sketch")
    _choice(bar, "sketchProfile", services.kernel.sketches[0].sketch_id)
    _number(bar, "distance", 8)
    _confirm(qtbot, window)
    half_volume = (30 * 6 + 24 * 6) * 8
    assert services.kernel.mass_properties().volume == pytest.approx(half_volume)
    bar = _start(window, "modify.body_transform")
    _choice(bar, "transformOperation", "copy")
    _number(bar, "move_x", 100)
    _pick(window, (12, 3, 8))
    _confirm(qtbot, window)
    bar = _start(window, "modify.body_transform")
    _choice(bar, "transformOperation", "mirror")
    _number(bar, "mirror_x", 50)
    _pick(window, (112, 3, 8))
    _confirm(qtbot, window)
    _start(window, "modify.boolean_bodies")
    _pick(window, (12, 3, 8))
    _pick(window, (-12, 3, 8), toggle=True)
    _confirm(qtbot, window)
    assert services.kernel.mass_properties().solid_count == 1
    assert services.kernel.mass_properties().volume == pytest.approx(2 * half_volume)
    _start(window, f"modify.{finish}")
    _pick(window, (-30, 15, 8), toggle=True)
    _pick(window, (30, 15, 8), toggle=True)
    assert window.viewport is not None
    selection = window.viewport.selection()
    assert selection is not None and len(selection.topology_ids) == 2
    if finish == "fillet":
        fillet = window.fillet_command_bar
        assert fillet is not None
        button = fillet.commit_button
        for text in ("999", "1"):
            fillet.radius_edit.selectAll()
            QTest.keyClicks(fillet.radius_edit, text)
            QTest.keyClick(fillet.radius_edit, Qt.Key.Key_Return)
            if text == "999":
                qtbot.waitUntil(
                    lambda: "当前半径无法生成圆角" in window.status_command.text(), timeout=30000
                )
                assert not button.isEnabled() and len(loaded.document.commands) == 5
        removed = 60 * (1 - math.pi / 4)
    else:
        bar = window.modeling_command_bar
        assert bar is not None
        button = bar.findChild(QPushButton, "modelingCommitButton")
        assert button is not None
        _number(bar, "distance", 999)
        qtbot.waitUntil(lambda: "预览失败" in window.status_command.text(), timeout=30000)
        assert not button.isEnabled() and len(loaded.document.commands) == 5
        _number(bar, "distance", 1)
        removed = 60 / 2
    _confirm(qtbot, window, button)
    expected = 2 * half_volume - removed
    assert services.kernel.mass_properties().volume == pytest.approx(expected)
    assert services.kernel.geometry_check().is_valid
    window.act_undo.trigger()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 5 and not unit.is_busy, timeout=30000)
    assert services.kernel.mass_properties().volume == pytest.approx(2 * half_volume)
    window.act_redo.trigger()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 6 and not unit.is_busy, timeout=30000)
    assert services.kernel.mass_properties().volume == pytest.approx(expected)
    _archive(
        qtbot, monkeypatch, window, services, tmp_path / f"bracket-{finish}.mc.json", expected, 1
    )


@pytest.mark.parametrize(
    ("kind", "angle"), [("linear", 360.0), ("circular", 360.0), ("circular", 180.0)]
)
def test_generic_body_array_with_unrelated_body_edit_undo_and_archive(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kind: str,
    angle: float,
) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1500, 950)
    window.show()
    window.act_new.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    for center, mode in (((20.0, 0.0, 0.0), "new"), ((50.0, 50.0, 0.0), "add")):
        bar = _start(window, "feature.box")
        for name, value in (("size_x", 4), ("size_y", 4), ("size_z", 8)):
            _number(bar, name, value)
        _choice(bar, "mode", mode)
        assert window.viewport is not None
        window.viewport.workplane_point_picked.emit(center, QPoint())
        _confirm(qtbot, window)
    assert services.kernel.mass_properties().solid_count == 2
    bar = _start(window, "modify.body_pattern")
    _choice(bar, "patternKind", kind)
    count = bar.findChild(QSpinBox, "body_pattern_count")
    assert count is not None
    count.setValue(3)
    if kind == "circular":
        _number(bar, "pattern_angle", angle)
    _pick(window, (20, 0, 4))
    _confirm(qtbot, window)

    def check_instances(count: int) -> None:
        from collections.abc import Sequence
        from typing import cast

        centers: list[tuple[float, ...]] = []
        for body in services.kernel.body_ids:
            center = cast(
                "Sequence[float]", services.kernel.interactive_body_selector(body)["center_mm"]
            )
            centers.append(tuple(round(value, 6) for value in center))
        expected = [(50.0, 50.0, 0.0)]
        for index in range(count):
            if kind == "linear":
                expected.append((20.0 + index * 10, 0.0, 0.0))
            else:
                radians = math.radians(angle * index / (count if angle == 360 else count - 1))
                expected.append(
                    (round(20 * math.cos(radians), 6), round(20 * math.sin(radians), 6), 0.0)
                )
        assert sorted(centers) == sorted(expected)
        assert services.kernel.geometry_check().is_valid
        assert services.kernel.mass_properties().volume == pytest.approx(128 * (count + 1))
        origins = services.kernel.viewport_data()[-1].body_origins
        assert sum(o.result.state_id == "modify.body_pattern:2" for o in origins) == count - 1

    check_instances(3)
    panel = window.right_panel
    assert panel is not None
    panel.select_feature_ordinal(2)
    edit = panel.findChild(QPushButton, "editHistoryFeature")
    assert edit is not None and edit.isEnabled()
    timestamp = loaded.document.commands[-1].timestamp_utc

    def revise_count() -> None:
        dialog = window.findChild(HistoryEditDialog)
        assert dialog is not None
        try:
            field = dialog.parameter_form.field_widget("pattern.count")
            assert isinstance(field, QSpinBox)
            field.setValue(4)
            dialog.reason_field.setText("通用实体阵列增加到四件，保留无关实体")
            dialog.preview_changes()
            qtbot.waitUntil(dialog.confirm_button.isEnabled, timeout=30000)
            dialog.confirm_changes()
        except BaseException:
            dialog.reject()
            raise

    QTimer.singleShot(0, revise_count)
    edit.click()
    qtbot.waitUntil(
        lambda: bool(loaded.document.commands[-1].amendments) and not unit.is_busy, timeout=30000
    )
    assert loaded.document.commands[-1].timestamp_utc == timestamp
    assert len(loaded.document.commands[-1].amendments) == 1
    check_instances(4)
    window.act_undo.trigger()
    qtbot.waitUntil(
        lambda: (
            len(loaded.document.commands) == 3
            and not loaded.document.commands[-1].amendments
            and not unit.is_busy
        ),
        timeout=30000,
    )
    check_instances(3)
    window.act_undo.trigger()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)
    assert services.kernel.mass_properties().solid_count == 2
    assert services.kernel.mass_properties().volume == pytest.approx(256)
    window.act_redo.trigger()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 3 and not unit.is_busy, timeout=30000)
    check_instances(3)
    window.act_redo.trigger()
    qtbot.waitUntil(
        lambda: bool(loaded.document.commands[-1].amendments) and not unit.is_busy,
        timeout=30000,
    )
    check_instances(4)
    _archive(
        qtbot, monkeypatch, window, services, tmp_path / f"array-{kind}-{angle}.mc.json", 640, 5
    )
    check_instances(4)
