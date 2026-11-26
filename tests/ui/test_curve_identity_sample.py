# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exercise the delivered legacy-curve sample through the drawing UI."""

import hashlib
import json
from pathlib import Path
from shutil import copyfile

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
from mycad.core.sketch import PolylineEntity, SplineEntity
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf
from mycad.ui.main_window import MainWindow


def test_delivered_legacy_curve_sample_opens_and_upgrades_through_ui(
    qtbot: QtBot, tmp_path: Path
) -> None:
    sample_dir = Path(__file__).parents[2] / ".omo/evidence/tolerance-legacy-curve-upgrade"
    source = sample_dir / "legacy-curves.my2d"
    manifest = json.loads((sample_dir / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest["sha256"]
    target = tmp_path / "legacy-curves.my2d"
    copyfile(source, target)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.open_document_path(target)
    qtbot.waitUntil(lambda: window.loaded_document() is not None, timeout=20000)
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not None, timeout=20000)
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.fit_view()
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        canvas.local_to_screen((0, -20)),
    )
    assert canvas.selected_entity_ids == {manifest["polyline_id"], manifest["spline_id"]}
    datum = services.kernel.drawing_datum_identifiers[0]
    frame = services.kernel.drawing_tolerance_frames[0]
    editor.drawing_command_bar.input.setText("CURVEIDUPGRADE")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    curves = services.kernel.sketches[0].entities
    assert isinstance(curves[0], PolylineEntity) and len(curves[0].point_ids) == 3
    assert isinstance(curves[1], SplineEntity) and len(curves[1].point_ids) == 4
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    window.request_undo()
    qtbot.waitUntil(
        lambda: all(
            not item.point_ids
            for item in services.kernel.sketches[0].entities
            if isinstance(item, PolylineEntity | SplineEntity)
        ),
        timeout=10000,
    )
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(
        lambda: all(
            bool(item.point_ids)
            for item in services.kernel.sketches[0].entities
            if isinstance(item, PolylineEntity | SplineEntity)
        ),
        timeout=10000,
    )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: not loaded.document.is_dirty, timeout=10000)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, target)
    restored = reopened.kernel.sketches[0].entities
    assert isinstance(restored[0], PolylineEntity) and len(restored[0].point_ids) == 3
    assert isinstance(restored[1], SplineEntity) and len(restored[1].point_ids) == 4
    assert reopened.kernel.drawing_datum_identifiers == (datum,)
    assert reopened.kernel.drawing_tolerance_frames == (frame,)
    entities = {entity.entity_id: entity for entity in reopened.kernel.sketches[0].entities}
    assert datum.attachment is not None and frame.leader_attachment is not None
    assert resolve_attachment_local(datum.attachment, entities) == (30, 0)
    assert resolve_attachment_local(frame.leader_attachment, entities) == (15, 0)

    frames = services.kernel.drawing_tolerance_frames
    datums = services.kernel.drawing_datum_identifiers
    anchors = tools.legacy_frame_export_anchors(frames)
    dxf = tmp_path / "upgraded.dxf"
    write_sketches_dxf(
        services.kernel.sketches,
        dxf,
        tolerance_frames=frames,
        datum_identifiers=datums,
        legacy_frame_anchors=anchors,
        legacy_frame_skipped_vertices=tools.legacy_frame_export_skipped_vertices(frames, anchors),
        legacy_frame_bounds=tools.legacy_frame_export_bounds(frames, anchors),
        legacy_datum_snapshots=tools.legacy_datum_export_snapshots(datums),
    )
    imported = read_sketch_dxf(dxf)
    imported_entities = {entity.entity_id: entity for entity in imported.sketch.entities}
    imported_datum = imported.datum_identifiers[0]
    imported_frame = imported.tolerance_frames[0]
    assert imported_datum.attachment is not None and imported_frame.leader_attachment is not None
    assert resolve_attachment_local(imported_datum.attachment, imported_entities) == (30, 0)
    assert resolve_attachment_local(imported_frame.leader_attachment, imported_entities) == (15, 0)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest["sha256"]
