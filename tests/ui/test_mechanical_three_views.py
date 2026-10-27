# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A real flange travels through placement, association, replay and both outputs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtPdf import QPdfDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.core.drawing_projection import ArcCurve
from mycad.core.drawing_references import reference_for_curve, resolve_reference
from mycad.ui.main_window import MainWindow


def test_flange_three_views_measure_edit_reopen_undo_and_export(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    plan = cast("dict[str, object]", json.loads(Path("examples/flange_plan.json").read_text()))
    steps = cast("list[dict[str, object]]", plan["steps"])
    for step in steps:
        loaded.bus.execute(
            cast("str", step["id"]), cast("dict[str, object]", step["params"]), "test"
        )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench = window.drawing_workbench
    unit = window.execution_unit
    assert unit is not None
    bench.scale.setValue(0.5)
    bench.title.setText("法兰三视图验收")
    bench.begin_placement()
    qtbot.waitUntil(lambda: bench.canvas.placing and not unit.is_busy, timeout=60000)

    def click(x: float, y: float) -> None:
        point = bench.canvas.mapFromScene(QPointF(x, -y))
        QTest.mouseMove(bench.canvas.viewport(), point)
        QTest.mouseClick(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)

    for point in ((90, 150), (90, 75), (200, 150)):
        click(*point)
    QTest.keyClick(bench.canvas, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: len(services.kernel.drawing_state.views) == 3 and not unit.is_busy)
    views = services.kernel.drawing_state.views
    top = next(v for v in views if v.direction == "top")
    assert services.kernel.drawing_state.effective_anchor(top.view_id)[1] < 150
    qtbot.waitUntil(
        lambda: all(bench.updates.status(v.view_id) == "clean" for v in views), timeout=60000
    )
    projection = bench.projections[top.view_id]
    outer = next(
        c
        for c in projection.curves
        if isinstance(c.geometry, ArcCurve) and abs(c.geometry.radius - 40) < 1e-6
    )
    # Same axis does not make an outward cylinder and an inward bore ambiguous.
    assert resolve_reference(reference_for_curve(outer), projection).status == "resolved"
    bench.annotations.begin("diameter")
    click(104, 75)  # r3 hole at x25, paper scale 1:2
    click(120, 55)
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_state.annotations) == 1 and not unit.is_busy
    )
    scene = bench.output_scene()
    assert scene.resolved_annotations[0].value == pytest.approx(6)
    bench.annotations.begin("diameter")
    click(110, 75)  # r40 outer rim
    click(130, 90)
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_state.annotations) == 2 and not unit.is_busy
    )
    assert sorted(
        a.value for a in bench.output_scene().resolved_annotations if a.value is not None
    ) == [6, 80]
    window.workspace_tabs.activate("model")
    original = loaded.document.commands[2]
    params = dict(original.params)
    base_hole = dict(cast("dict[str, object]", params["base_hole"]))
    params["base_hole"] = {**base_hole, "diameter": 8}
    assert unit.submit(
        lambda: loaded.bus.edit_and_replay(2, params, "test", "hole diameter"),
        operation="edit-model",
        session_id=bench.session_id,
    )
    qtbot.waitUntil(lambda: not unit.is_busy)
    window.workspace_tabs.activate("drawing")
    qtbot.waitUntil(
        lambda: (
            all(bench.updates.status(v.view_id) == "clean" for v in views)
            and bench.projections[top.view_id].source_fingerprint
            == services.kernel.drawing_source_fingerprint
        ),
        timeout=60000,
    )
    assert sorted(
        a.value for a in bench.output_scene().resolved_annotations if a.value is not None
    ) == [8, 80]
    archive = tmp_path / "flange.my3d"

    def save_name(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(archive), "MyCAD 三维零件 (*.my3d)"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_name)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", save_name)
    window.act_save.trigger()
    assert archive.exists()
    saved = archive.read_bytes()
    session = bench.session_id
    window.act_open.trigger()
    qtbot.waitUntil(lambda: bench.session_id != session and not unit.is_busy, timeout=60000)
    qtbot.waitUntil(
        lambda: all(bench.updates.status(v.view_id) == "clean" for v in views), timeout=60000
    )
    window.workspace_tabs.activate("drawing")
    assert archive.read_bytes() == saved
    reopened = window.loaded_document()
    assert reopened is not None
    assert reopened.document.commands[2].timestamp_utc == original.timestamp_utc
    window.request_undo()
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_state.annotations) == 1 and not unit.is_busy
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_state.annotations) == 2 and not unit.is_busy
    )
    qtbot.waitUntil(
        lambda: all(bench.updates.status(v.view_id) == "clean" for v in views), timeout=60000
    )
    folder = Path(os.environ.get("MYCAD_ACCEPTANCE_OUTPUT", str(tmp_path)))
    for kind in ("dxf", "pdf"):
        target = folder / f"flange-three-views.{kind}"
        bench.export_to(kind, target)
        qtbot.waitUntil(lambda target=target: target.exists() and not unit.is_busy, timeout=30000)
    assert "⌀8.00 mm" in (folder / "flange-three-views.dxf").read_text()
    pdf = QPdfDocument()
    assert pdf.load(str(folder / "flange-three-views.pdf")) == QPdfDocument.Error.None_
    assert "⌀8.00 mm" in pdf.getAllText(0).text()
    assert "⌀80.00 mm" in pdf.getAllText(0).text()
    assert window.grab().save(str(folder / "flange-three-views-desktop.png"))
