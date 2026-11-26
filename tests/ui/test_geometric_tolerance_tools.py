# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Canvas geometric tolerance tools operate through the document history."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QImage, QPainter, QPainterPath, QTextLayout
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMenu, QMessageBox
from pytest import MonkeyPatch, fixture
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.geometric_tolerance import (
    AnnotationAttachment,
    DatumAttachment,
    DatumIdentifier,
    FeatureControlFrame,
    SurfaceIndication,
    ToleranceRow,
)
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf
from mycad.ui.document_session import DocumentSession
from mycad.ui.geometric_tolerance_dialog import GeometricToleranceDialog
from mycad.ui.geometric_tolerance_tools import GeometricToleranceTools
from mycad.ui.main_window import MainWindow


@fixture(autouse=True)
def _clear_clipboard_before_qt_teardown(qtbot: QtBot) -> Iterator[None]:
    """Release clipboard-owned Qt wrappers while the QApplication is still alive."""
    yield
    QApplication.clipboard().clear()


def _accept_preview(_dialog: QDialog) -> int:
    return int(QDialog.DialogCode.Accepted)


def _no_glyph_paths(_layout: object) -> tuple[QPainterPath, ...]:
    return ()


def _confirm_yes(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
    return QMessageBox.StandardButton.Yes


def _label_a(*_args: object, **_kwargs: object) -> tuple[str, bool]:
    return "A", True


def _label_b(*_args: object, **_kwargs: object) -> tuple[str, bool]:
    return "B", True


def _text_response(value: str, *, accepted: bool = True) -> Callable[..., tuple[str, bool]]:
    def respond(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return value, accepted

    return respond


def _next_response[T](values: Iterator[T]) -> Callable[..., tuple[T, bool]]:
    def respond(*_args: object, **_kwargs: object) -> tuple[T, bool]:
        return next(values), True

    return respond


def _fail_draft_apply(*_args: object, **_kwargs: object) -> bool:
    return False


def _missing_glyph(*_args: object, **_kwargs: object) -> str:
    return "字"


def _unsnapped(point: tuple[float, float]) -> tuple[tuple[float, float], bool]:
    return point, False


def _save_response(path: str, choice: str) -> Callable[..., tuple[str, str]]:
    def respond(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return path, choice

    return respond


def _private_member(instance: object, name: str) -> object:
    """Access internal seams exercised by these integration tests."""
    return getattr(instance, name)


def _select_annotation(
    tools: GeometricToleranceTools, identity: str, kind: str, *, additive: bool = False
) -> bool:
    select = cast("Callable[..., bool]", vars(type(tools))["_select"])
    return select(tools, identity, kind, additive=additive)


def _place_annotation(
    tools: GeometricToleranceTools,
    kind: Literal["frame", "datum", "mixed"],
    point: tuple[float, float],
) -> None:
    name = {"frame": "_place_frame_grip", "datum": "_place_datum_grip", "mixed": "_place_mixed"}[
        kind
    ]
    place = cast(
        "Callable[[GeometricToleranceTools, tuple[float, float]], None]", vars(type(tools))[name]
    )
    place(tools, point)


def _surface_grip(
    target: tuple[float, float],
    indication: SurfaceIndication,
    index: int,
    point: tuple[float, float],
) -> SurfaceIndication:
    name = "_surface_with_grip"
    operation = cast(
        "Callable[[tuple[float, float], SurfaceIndication, int, tuple[float, float]], SurfaceIndication]",
        getattr(GeometricToleranceTools, name),
    )
    return operation(target, indication, index, point)


def _frame_grip_value(
    frame: FeatureControlFrame, index: int, point: tuple[float, float]
) -> FeatureControlFrame:
    name = "_frame_with_grip"
    operation = cast(
        "Callable[[FeatureControlFrame, int, tuple[float, float]], FeatureControlFrame]",
        getattr(GeometricToleranceTools, name),
    )
    return operation(frame, index, point)


def _leader_target_overlap(item: FeatureControlFrame | DatumIdentifier) -> bool:
    name = "_leader_target_overlaps_vertex"
    operation = cast(
        "Callable[[FeatureControlFrame | DatumIdentifier], bool]",
        getattr(GeometricToleranceTools, name),
    )
    return operation(item)


def _leader_vertex_overlap(
    item: FeatureControlFrame | DatumIdentifier, index: int, point: tuple[float, float]
) -> bool:
    name = "_leader_vertex_overlaps_neighbor"
    operation = cast(
        "Callable[[FeatureControlFrame | DatumIdentifier, int, tuple[float, float]], bool]",
        getattr(GeometricToleranceTools, name),
    )
    return operation(item, index, point)


def test_mechanical_datum_selects_target_then_position_before_name(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    calls: list[tuple[object, ...]] = []

    def ask(*args: object, **kwargs: object) -> tuple[str, bool]:
        calls.append(args)
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", ask)
    tools.begin_mechanical_datum()
    assert tools.pending and not calls
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    assert not calls and not services.kernel.drawing_datum_identifiers
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    assert len(calls) == 1
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.target_mm == pytest.approx((0, 0))
    assert datum.position_mm == pytest.approx((10, 10))
    assert not tools.pending


def test_detach_datum_from_annotation_preserves_target(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", frame.frame_id, (0, 0)),
    )
    assert tools.execute is not None
    assert tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=tools.datum_screen_bounds(datum).center().toPoint(),
    )
    tools.detach_selected_datum()
    changed = services.kernel.drawing_datum_identifiers[0]
    assert changed.annotation_attachment is None and changed.target_mm == datum.target_mm


def test_mechanical_datum_attaches_to_existing_frame(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools, canvas = editor.canvas.geometric_tolerance_tools, editor.canvas
    source = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0), rotation_deg=30
    )
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch", {"add_frames": [source.to_mapping()]}
    )
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_mechanical_datum()
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(source).center().toPoint()
    )
    assert tools.handle_command("30,25")
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.annotation_attachment is not None
    assert datum.annotation_attachment.kind == "frame"
    assert datum.annotation_attachment.object_id == source.frame_id
    assert datum.attachment is None


def test_mechanical_frame_attaches_to_reference_dimension(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.detached_dimension_layout import layout_reference_dimension

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools, canvas = editor.canvas.geometric_tolerance_tools, editor.canvas
    dimension = DetachedDimension(uuid4().hex, "aligned", (0, 0), (20, 0), (0, 5), 0, 20)
    assert tools.execute is not None and tools.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}
    )
    tools.begin_mechanical_frame()
    label = layout_reference_dimension(dimension, canvas).label.center().toPoint()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=label)

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    assert tools.handle_command("30,25")
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.leader_annotation_attachment is not None
    assert frame.leader_annotation_attachment.kind == "reference_dimension"
    assert frame.leader_annotation_attachment.object_id == dimension.dimension_id


def test_mechanical_datum_attaches_to_sketch_dimension(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=20,
        unit="mm",
        position_mm=(0, 5),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools, canvas = editor.canvas.geometric_tolerance_tools, editor.canvas
    labels = canvas.dimension_label_rectangles()
    assert dim.constraint_id in labels
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_mechanical_datum()
    hit = cast(
        "Callable[..., tuple[DatumAttachment | None, AnnotationAttachment | None, tuple[float, float] | None]]",
        _private_member(tools, "_pick_target"),
    )(canvas.screen_to_local(QPointF(labels[dim.constraint_id].center())))
    assert hit[1] is not None and hit[1].kind == "sketch_dimension", editor.status_label.text()
    assert canvas.rect().contains(labels[dim.constraint_id].center().toPoint()), (
        canvas.rect(),
        labels[dim.constraint_id],
    )
    assert vars(canvas)["_selection_anchor"] is None
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=labels[dim.constraint_id].center().toPoint()
    )
    assert tools.mechanical_datum_target is not None, editor.status_label.text()
    assert tools.handle_command("30,25")
    assert services.kernel.drawing_datum_identifiers, editor.status_label.text()
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.annotation_attachment is not None
    assert datum.annotation_attachment.kind == "sketch_dimension"
    assert datum.annotation_attachment.object_id == dim.constraint_id
    assert datum.annotation_attachment.anchor == "text"


def test_datum_reattaches_to_frame(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools, canvas = editor.canvas.geometric_tolerance_tools, editor.canvas
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(uuid4().hex, "A", (25, 25), (10, 15))
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    tools.begin_reattach()
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.annotation_attachment is not None
    assert updated.annotation_attachment.object_id == frame.frame_id
    assert updated.attachment is None


def test_move_datum_attached_to_frame_keeps_target(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools, canvas = editor.canvas.geometric_tolerance_tools, editor.canvas
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (25, 25),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", frame.frame_id, (0, 0)),
    )
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    assert (
        tools.handle_command("MOVE") and tools.handle_command("0,0") and tools.handle_command("5,3")
    )
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.position_mm == (30, 28) and moved.target_mm == (0, 0)


def test_ambiguous_annotation_target_does_not_start_placement(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools, canvas = editor.canvas.geometric_tolerance_tools, editor.canvas
    first = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0))
    second = FeatureControlFrame(uuid4().hex, first.rows, (0, 0))
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch", {"add_frames": [first.to_mapping(), second.to_mapping()]}
    )
    tools.begin_mechanical_datum()
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(first).center().toPoint()
    )
    assert tools.mechanical_datum_target is None
    assert "不唯一" in editor.status_label.text()
    assert tools.cancel()


def test_missing_annotation_attachment_is_reported(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools, canvas = editor.canvas.geometric_tolerance_tools, editor.canvas
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", uuid4().hex, (0, 0)),
    )
    tools.sync((), (datum,))
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    assert "失关联" in editor.status_label.text()
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_annotation_attachment=AnnotationAttachment("frame", uuid4().hex, (0, 0)),
    )
    assert cast("Callable[..., bool]", _private_member(tools, "_frame_attachment_lost"))(frame)


def test_array_member_rotation_ui_preserves_normal_side(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    import math
    from uuid import uuid4

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    target = LineEntity(uuid4().hex, (5, 0), (15, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    source_ref, target_ref = (
        ArrayEntityRef(sketch.sketch_id, source.entity_id),
        ArrayEntityRef(sketch.sketch_id, target.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(target.entity_id, "start")
        ),
        leader_offsets=((-15, -16),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_entity_ids = {target.entity_id}
    inputs = iter(("120", "5,0"))
    monkeypatch.setattr(QInputDialog, "getText", _next_response(inputs))
    change = vars(type(window))["_change_selected_associative_array"]
    change(window, mode="member_rotation")
    qtbot.waitUntil(
        lambda: not unit.is_busy and loaded.document.commands[-1].id == "drawing.array.rotate",
        timeout=15000,
    )
    assert loaded.document.commands[-1].version == 3
    changed = services.kernel.drawing_datum_identifiers[0]
    offset = changed.leader_offsets[-1]
    assert (
        changed.position_mm[0] + offset[0] - changed.target_mm[0],
        changed.position_mm[1] + offset[1] - changed.target_mm[1],
    ) == pytest.approx((-2 * math.sqrt(3), -2))


def test_array_resize_ui_preserves_lost_attachment(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    from uuid import uuid4

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 5, 0)) for x in (0, 10, 20))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        10,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (30, 20),
        (20, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(lines[2].entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_entity_ids = {lines[0].entity_id}
    inputs = iter((1, 2))
    monkeypatch.setattr(QInputDialog, "getInt", _next_response(inputs))
    change = vars(type(window))["_change_selected_associative_array"]
    change(window, mode="resize")
    qtbot.waitUntil(
        lambda: not unit.is_busy and loaded.document.commands[-1].id == "drawing.array.resize",
        timeout=15000,
    )
    assert loaded.document.commands[-1].version == 16
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_array_replacement_ui_reports_attached_annotation(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    target = LineEntity(uuid4().hex, (5, 0), (15, 0))
    replacement = LineEntity(uuid4().hex, (30, 0), (30, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target, replacement))
    source_ref, target_ref = (
        ArrayEntityRef(sketch.sketch_id, source.entity_id),
        ArrayEntityRef(sketch.sketch_id, target.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(target.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_entity_ids = {target.entity_id}

    def choose(
        _parent: object, _title: str, _label: str, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        return next(label for label in items if replacement.entity_id[:8] in label), True

    monkeypatch.setattr(QInputDialog, "getItem", choose)
    monkeypatch.setattr(QInputDialog, "getText", _text_response("30,0"))
    count = loaded.document.command_count
    change = vars(type(window))["_change_selected_associative_array"]
    change(window, mode="member_replace")
    qtbot.waitUntil(
        lambda: not unit.is_busy and "解除附着" in window.status_command.text(), timeout=15000
    )
    assert loaded.document.command_count == count
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_array_reset_ui_reports_lost_attachment(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    target = LineEntity(uuid4().hex, (5, 0), (15, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source_ref, target_ref = (
        ArrayEntityRef(sketch.sketch_id, source.entity_id),
        ArrayEntityRef(sketch.sketch_id, target.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(target.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    loaded.bus.execute(
        "drawing.array.erase",
        {"array_id": array.array_id, "targets": [target_ref.to_mapping()]},
        "local",
        version=2,
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_entity_ids = {source.entity_id}
    count = loaded.document.command_count
    change = vars(type(window))["_change_selected_associative_array"]
    change(window, mode="reset_overrides")
    qtbot.waitUntil(
        lambda: not unit.is_busy and "失关联" in window.status_command.text(), timeout=15000
    )
    assert loaded.document.command_count == count
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)


@pytest.mark.parametrize("normal", [False, True])
def test_dimension_preview_and_apply_preserves_normal_attachment(
    qtbot: QtBot, normal: bool
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-20, -16),),
        leader_auto_normal=normal,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["horizontal"].click()
    for point in ((5, 0), (5, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    editor.dimensions.value_editor.setValue(12)
    constraint = editor.dimensions.candidate
    assert constraint is not None and editor.dimensions.original is not None
    original = editor.dimensions.original
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, constraint) is not None, timeout=15000
    )
    preview = editor.dimensions.accepted_preview(original, constraint)
    assert preview is not None and preview.status == "success"
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(
        lambda: not unit.is_busy and loaded.document.commands[-1].id == "sketch.constraint.add",
        timeout=15000,
    )
    assert loaded.document.commands[-1].version == 10
    assert services.kernel.drawing_datum_identifiers[0].leader_auto_normal is normal


def test_drawing_revision_entry_preserves_normal_side(qtbot: QtBot) -> None:
    import math
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-10, -6),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(sketch, entities=(replace(line, end_mm=(-5, 5 * math.sqrt(3))),))
    state = changed.to_state_mapping()
    revisions = [
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise"
    assert loaded.document.commands[-1].version == 56
    updated = services.kernel.drawing_datum_identifiers[0]
    offset = updated.leader_offsets[-1]
    assert (
        updated.position_mm[0] + offset[0],
        updated.position_mm[1] + offset[1],
    ) == pytest.approx((-2 * math.sqrt(3), -2))


@pytest.mark.parametrize(
    "kind", ["exact", "unsafe", "edit", "unrelated_array", "unrelated_tangency"]
)
def test_drawing_revision_entry_preserves_exact_polyline_reorder(qtbot: QtBot, kind: str) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import CircleEntity, LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    array: AssociativeRectArray | None = None
    relation: CrossSketchTangency | None = None
    if kind == "unrelated_array":
        source = LineEntity(uuid4().hex, (30, 0), (40, 0))
        target = LineEntity(uuid4().hex, (30, 20), (40, 20))
        source_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
        target_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
        for item in (source_sketch, target_sketch):
            app.commit_new_sketch(services, loaded, item, session_identity=0)
        source_ref = ArrayEntityRef(source_sketch.sketch_id, source.entity_id)
        target_ref = ArrayEntityRef(target_sketch.sketch_id, target.entity_id)
        array = AssociativeRectArray(
            uuid4().hex,
            source_sketch.frame,
            2,
            1,
            20,
            0,
            (source_ref,),
            (ArrayMember(source_ref, target_ref, 1, 0),),
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    if kind == "unrelated_tangency":
        line = LineEntity(uuid4().hex, (20, 0), (30, 0))
        circle = CircleEntity(uuid4().hex, (25, 2), 2)
        line_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
        circle_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        for item in (line_sketch, circle_sketch):
            app.commit_new_sketch(services, loaded, item, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(line_sketch.sketch_id, line.entity_id),
            CrossSketchRef(circle_sketch.sketch_id, circle.entity_id),
            "line_left",
        )
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(polyline.entity_id, "segment", 0), 0.25, 2
    )
    datum = DatumIdentifier(uuid4().hex, "A", (4, 8), (2.5, 0), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    points = (
        tuple(reversed(polyline.points_mm))
        if kind in ("exact", "unrelated_array", "unrelated_tangency")
        else ((10, 0), (0, 0), (20, 20))
        if kind == "unsafe"
        else ((0, 0), (10, 0), (10, 12))
    )
    changed = replace(polyline, points_mm=points)
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    revisions = [
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    if kind == "unsafe":
        assert loaded.document.commands[-1].id == "drawing.tolerance.batch"
        assert "附着" in editor.status_label.text()
        assert services.kernel.sketches[0].entities == (polyline,)
        assert services.kernel.drawing_datum_identifiers == (datum,)
        return
    if kind == "edit":
        assert loaded.document.commands[-1].id == "sketch.revise", editor.status_label.text()
        assert services.kernel.sketches[0].entities == (changed,)
        assert services.kernel.drawing_datum_identifiers == (datum,)
        return
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 57
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 1
    assert updated.attachment.parameter == 0.75 and updated.target_mm == pytest.approx((2.5, 0))
    if array is not None:
        assert services.kernel.associative_arrays == (array,)
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_drawing_revision_entry_uses_identity_aware_version(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance_topology import prepare_curve_identity_upgrade
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    record = prepare_curve_identity_upgrade(sketch, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    current = services.kernel.sketches[0]
    updated = replace(
        current,
        entities=(
            replace(curve, points_mm=((0, 0), (10, 0), (11, 12)), point_ids=record.point_ids),
        ),
    )
    state = updated.to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 64
    assert services.kernel.sketches == (updated,)


def test_select_unresolved_frame_reports_recovery(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A"),)),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_annotation_attachment=AnnotationAttachment("frame", uuid4().hex, (0, 0)),
    )
    tools.sync((frame,), ())
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert tools.selected_id == frame.frame_id
    assert "失关联" in editor.status_label.text()
    assert "DETACHFRAME" in editor.status_label.text()
    assert "基准 A 未关联" in editor.status_label.text()


def test_mechanical_datum_coordinate_input_and_cancel(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    defaults: list[str] = []

    def ask(*_args: object, **kwargs: object) -> tuple[str, bool]:
        defaults.append(str(kwargs.get("text")))
        return defaults[-1], True

    monkeypatch.setattr(QInputDialog, "getText", ask)
    assert tools.handle_command("AMDATUMID")
    assert tools.handle_command("1,2")
    assert tools.handle_command("@10,5")
    first = services.kernel.drawing_datum_identifiers[0]
    assert first.target_mm == (1, 2) and first.position_mm == (11, 7)
    assert defaults == ["A"]
    tools.begin_mechanical_datum()
    assert tools.handle_command("5,5")
    assert tools.handle_command("10,10")
    assert defaults == ["A", "B"]
    second = services.kernel.drawing_datum_identifiers[1]
    tools.begin_mechanical_datum()
    assert tools.handle_command("0,0")
    assert tools.cancel()
    assert not tools.pending and services.kernel.drawing_datum_identifiers == (first, second)


def test_mechanical_datum_without_leader_can_be_placed_and_moved(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools, canvas = editor.canvas.geometric_tolerance_tools, editor.canvas
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    assert tools.handle_command("AMDATUMID")
    assert tools.handle_command("N")
    assert tools.handle_command("10,10")
    datum = services.kernel.drawing_datum_identifiers[0]
    assert not datum.leader_visible
    assert tools.datum_screen_path(datum)[0] == ()
    assert (
        len(
            cast(
                "Callable[..., tuple[tuple[int, tuple[float, float]], ...]]",
                _private_member(tools, "_datum_grips"),
            )(datum)
        )
        == 1
    )
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(datum.position_mm)
    )
    assert tools.handle_command("20,20")
    changed = services.kernel.drawing_datum_identifiers[0]
    assert changed.position_mm == (20, 20) and not changed.leader_visible


def test_datum_shared_layout_matches_exported_box(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement
    from ezdxf.document import Drawing
    from ezdxf.entities.insert import Insert
    from ezdxf.entities.line import Line

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    for label in ("A", "LONG基准"):
        datum = DatumIdentifier(
            uuid4().hex, label, (10.31, 10.17), (0.23, -0.13), layout_mode="shared"
        )
        rect = tools.datum_screen_bounds(datum)
        path = tmp_path / f"{label}.dxf"
        write_sketches_dxf((), path, datum_identifiers=(datum,))
        readfile = cast("Callable[[Path], Drawing]", vars(ezdxf.filemanagement)["readfile"])
        document = readfile(path)
        restored = read_sketch_dxf(path).datum_identifiers[0]
        assert restored.layout_mode == "shared"
        assert restored.position_mm == pytest.approx(datum.position_mm)
        assert restored.target_mm == pytest.approx(datum.target_mm)
        insert = cast("Insert", document.modelspace().query("INSERT")[0])
        all_lines = tuple(
            cast("Line", item) for item in document.blocks[insert.dxf.name].query("LINE")
        )
        lines = all_lines[-4:]
        width = max(float(item.dxf.start.x) for item in lines)
        height = -min(float(item.dxf.start.y) for item in lines)
        assert rect.width() / editor.canvas.view_scale == pytest.approx(width)
        assert rect.height() / editor.canvas.view_scale == pytest.approx(height)
        leader, triangle = tools.datum_screen_path(datum)
        native = all_lines[0]
        start_world = (
            datum.position_mm[0] + native.dxf.start.x,
            datum.position_mm[1] + native.dxf.start.y,
        )
        assert editor.canvas.screen_to_local(leader[0]) == pytest.approx(start_world, abs=1e-8)
        assert triangle


def test_datum_shared_layout_matches_export_after_style_change(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement
    from ezdxf.document import Drawing
    from ezdxf.entities.insert import Insert
    from ezdxf.entities.line import Line

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    assert editor.canvas.text_tools is not None
    style = TextStyle("large", "大字", font_family="DejaVu Sans", height_mm=7, width_factor=1.5)
    table = TextStyleTable((style,), "large")
    editor.canvas.text_tools.sync((), table)
    datum = DatumIdentifier(
        uuid4().hex, "ABC", (3, 4), (0, 0), text_style_id="large", layout_mode="shared"
    )
    rect = editor.canvas.geometric_tolerance_tools.datum_screen_bounds(datum)
    path = tmp_path / "style.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,), text_styles=table)
    readfile = cast("Callable[[Path], Drawing]", vars(ezdxf.filemanagement)["readfile"])
    document = readfile(path)
    insert = cast("Insert", document.modelspace().query("INSERT")[0])
    lines = tuple(cast("Line", item) for item in document.blocks[insert.dxf.name].query("LINE"))[
        -4:
    ]
    assert rect.width() / editor.canvas.view_scale == pytest.approx(
        max(float(x.dxf.start.x) for x in lines)
    )
    assert rect.height() / editor.canvas.view_scale == pytest.approx(
        -min(float(x.dxf.start.y) for x in lines)
    )


def test_mechanical_datum_mouse_obeys_orthogonal_mode(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    canvas.set_orthogonal_enabled(True)
    tools.begin_mechanical_datum()
    assert tools.handle_command("0,0")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 4)))
    assert services.kernel.drawing_datum_identifiers[0].position_mm == (10, 0)


def test_attached_datum_first_vertex_is_normal_to_sloped_line(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    editor = window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 20))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    canvas.set_orthogonal_enabled(True)
    tools.begin_mechanical_datum()
    assert tools.handle_command("0,0")
    assert tools.handle_command("V")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((4, 8)))
    assert tools.mechanical_datum_vertices[0] == pytest.approx((-2, 2))
    assert tools.handle_command("10,10")
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.leader_auto_normal
    vertex = (
        datum.position_mm[0] + datum.leader_offsets[-1][0],
        datum.position_mm[1] + datum.leader_offsets[-1][1],
    )
    assert vertex == pytest.approx((-2, 2))
    path, _ = tools.datum_screen_path(datum)
    last = path[-1] - path[-2]
    assert last.x() == pytest.approx(last.y())
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    tools.detach_selected_datum()
    detached = services.kernel.drawing_datum_identifiers[0]
    assert detached.attachment is None and not detached.leader_auto_normal


def test_mechanical_datum_box_position_uses_object_snap(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    editor = window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (10, 4), (20, 4))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_mechanical_datum()
    assert tools.handle_command("0,0")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10.8, 4.4)))
    assert services.kernel.drawing_datum_identifiers[0].position_mm == (10, 4)


def test_mechanical_datum_with_intermediate_vertex(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_mechanical_datum()
    assert tools.handle_command("0,0")
    assert tools.handle_command("V")
    assert tools.handle_command("0,10")
    assert tools.handle_command("10,10")
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.leader_offsets == ((-10, 0),)
    assert datum.position_mm == (10, 10)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_leader_rejects_duplicate_vertex_without_leaving_command(
    qtbot: QtBot, owner: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools.handle_command("AMDATUMID" if owner == "datum" else "AMFCFRAME")
    for value in ("0,0", "V", "0,0"):
        assert tools.handle_command(value)
    vertices = (
        tools.mechanical_datum_vertices if owner == "datum" else tools.mechanical_frame_vertices
    )
    assert not vertices
    assert "重合" in editor.canvas.message
    assert tools.handle_command("0,10")
    assert vertices == [(0, 10)]
    assert tools.handle_command("V")
    assert tools.handle_command("0,10")
    assert vertices == [(0, 10)]
    assert "重合" in editor.canvas.message
    assert tools.handle_command("10,10")
    assert vertices == [(0, 10), (10, 10)]


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_leader_mouse_rejects_duplicate_vertex(qtbot: QtBot, owner: str) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    assert tools.handle_command("AMDATUMID" if owner == "datum" else "AMFCFRAME")
    target = canvas.local_to_screen((0, 0))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=target)
    assert tools.handle_command("V")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=target)
    vertices = (
        tools.mechanical_datum_vertices if owner == "datum" else tools.mechanical_frame_vertices
    )
    assert not vertices and "重合" in canvas.message
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 10)))
    assert len(vertices) == 1


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_annotation_creation_rejects_layer_hidden_in_dialog(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    from dataclasses import replace

    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    canvas = editor.canvas
    canvas.set_layer_table(layers, "GDT")
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    assert tools.handle_command("AMDATUMID" if owner == "datum" else "AMFCFRAME")
    assert tools.handle_command("0,0")

    def hide() -> None:
        hidden = replace(
            layers,
            layers=tuple(
                replace(layer, visible=False) if layer.name == "GDT" else layer
                for layer in layers.layers
            ),
        )
        loaded.bus.execute(
            "drawing.layers.set", {"layers": hidden.to_mapping(), "dimension_layer": "DIM"}, "local"
        )

    def label(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        hide()
        return "A", True

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        hide()
        dialog.accept()

    if owner == "datum":
        monkeypatch.setattr(QInputDialog, "getText", label)
    else:
        QTimer.singleShot(20, accept)
    assert tools.handle_command("20,20")
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_datum_identifiers
    assert "隐藏" in canvas.message
    assert tools.pending
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    if owner == "datum":
        monkeypatch.setattr(QInputDialog, "getText", _label_a)
    else:

        def accept_retry() -> None:
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, GeometricToleranceDialog)
            dialog.accept()

        QTimer.singleShot(20, accept_retry)
    assert tools.handle_command("20,20")
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert len(items) == 1 and not tools.pending
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_datum_identifiers
    assert not services.kernel.drawing_tolerance_frames


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_classic_annotation_placement_rejects_hidden_layer(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    from dataclasses import replace

    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    canvas = editor.canvas
    canvas.set_layer_table(layers, "GDT")
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    if owner == "datum":
        monkeypatch.setattr(QInputDialog, "getText", _label_a)
        tools.begin_datum()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20, 20)))
    else:

        def accept() -> None:
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, GeometricToleranceDialog)
            dialog.accept()

        QTimer.singleShot(20, accept)
        tools.begin_frame()
    hidden = replace(
        layers,
        layers=tuple(
            replace(layer, visible=False) if layer.name == "GDT" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": hidden.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    count = loaded.document.command_count
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    assert loaded.document.command_count == count
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_datum_identifiers
    assert "隐藏" in canvas.message and tools.pending
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert len(items) == 1 and not tools.pending
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_datum_identifiers
    assert not services.kernel.drawing_tolerance_frames


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_leader_vertex_grip_rejects_target_overlap(qtbot: QtBot, owner: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    if owner == "frame":
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (20, 20),
            leader_target_mm=(0, 0),
            leader_offsets=((-10, -10),),
            leader_anchor_offset=(0, -2),
        )
        assert tools.execute is not None
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [item.to_mapping()]})
        tools.frame_grip = (item, 0)
    else:
        item = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), leader_offsets=((-10, -10),))
        assert tools.execute is not None
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [item.to_mapping()]})
        tools.datum_grip = (item, 0)
    count = loaded.document.command_count
    if owner == "frame":
        _place_annotation(tools, "frame", (0, 0))
        assert services.kernel.drawing_tolerance_frames == (item,)
    else:
        _place_annotation(tools, "datum", (0, 0))
        assert services.kernel.drawing_datum_identifiers == (item,)
    assert loaded.document.command_count == count
    assert "重合" in editor.canvas.message
    if owner == "frame":
        assert tools.frame_grip is not None
        _place_annotation(tools, "frame", (10, 5))
        assert services.kernel.drawing_tolerance_frames[0].leader_offsets == ((-10, -15),)
    else:
        assert tools.datum_grip is not None
        _place_annotation(tools, "datum", (10, 5))
        assert services.kernel.drawing_datum_identifiers[0].leader_offsets == ((-10, -15),)
    loaded.bus.undo_operation()
    if owner == "frame":
        assert services.kernel.drawing_tolerance_frames == (item,)
    else:
        assert services.kernel.drawing_datum_identifiers == (item,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_leader_grip_rejects_unsynchronized_object_change(qtbot: QtBot, owner: str) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    if owner == "frame":
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (20, 20),
            leader_target_mm=(0, 0),
            leader_offsets=((-10, -10),),
            leader_anchor_offset=(0, -2),
        )
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [item.to_mapping()]})
        tools.frame_grip = (item, 0)
        changed = replace(item, position_mm=(30, 20))
        params = {"update_frames": [changed.to_mapping()]}
    else:
        item = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), leader_offsets=((-10, -10),))
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [item.to_mapping()]})
        tools.datum_grip = (item, 0)
        changed = replace(item, position_mm=(30, 20))
        params = {"update_datums": [changed.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params, "local")
    count = loaded.document.command_count
    if owner == "frame":
        _place_annotation(tools, "frame", (10, 5))
        assert services.kernel.drawing_tolerance_frames == (changed,)
    else:
        _place_annotation(tools, "datum", (10, 5))
        assert services.kernel.drawing_datum_identifiers == (changed,)
    assert loaded.document.command_count == count
    assert "改变" in editor.canvas.message


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_leader_target_grip_rejects_vertex_overlap(qtbot: QtBot, owner: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    if owner == "frame":
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (20, 20),
            leader_target_mm=(0, 0),
            leader_offsets=((-10, -10),),
            leader_anchor_offset=(0, -2),
        )
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [item.to_mapping()]})
        tools.frame_grip = (item, -2)
    else:
        item = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), leader_offsets=((-10, -10),))
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [item.to_mapping()]})
        tools.datum_grip = (item, -2)
    count = loaded.document.command_count
    if owner == "frame":
        _place_annotation(tools, "frame", (10, 10))
        assert services.kernel.drawing_tolerance_frames == (item,)
    else:
        _place_annotation(tools, "datum", (10, 10))
        assert services.kernel.drawing_datum_identifiers == (item,)
    assert loaded.document.command_count == count
    assert "重合" in editor.canvas.message


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("state", ["hidden", "locked", "frozen"])
@pytest.mark.parametrize("sync", [True, False])
def test_leader_grip_does_not_edit_layer_hidden_mid_operation(
    qtbot: QtBot, owner: str, state: str, sync: bool
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    if owner == "frame":
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (20, 20),
            layer_name="GDT",
            leader_target_mm=(0, 0),
            leader_offsets=((-10, -10),),
            leader_anchor_offset=(0, -2),
        )
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [item.to_mapping()]})
        tools.frame_grip = (item, 0)
    else:
        item = DatumIdentifier(
            uuid4().hex, "A", (20, 20), (0, 0), layer_name="GDT", leader_offsets=((-10, -10),)
        )
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [item.to_mapping()]})
        tools.datum_grip = (item, 0)
    hidden = replace(
        layers,
        layers=tuple(
            replace(
                layer,
                visible=state != "hidden",
                locked=state == "locked",
                frozen=state == "frozen",
            )
            if layer.name == "GDT"
            else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": hidden.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    if sync:
        cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    count = loaded.document.command_count
    if owner == "frame":
        _place_annotation(tools, "frame", (10, 5))
        assert services.kernel.drawing_tolerance_frames == (item,)
    else:
        _place_annotation(tools, "datum", (10, 5))
        assert services.kernel.drawing_datum_identifiers == (item,)
    assert loaded.document.command_count == count
    assert "隐藏" in editor.canvas.message
    assert (tools.frame_grip if owner == "frame" else tools.datum_grip) is not None
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    if owner == "frame":
        _place_annotation(tools, "frame", (10, 5))
        assert services.kernel.drawing_tolerance_frames[0].leader_offsets == ((-10, -15),)
    else:
        _place_annotation(tools, "datum", (10, 5))
        assert services.kernel.drawing_datum_identifiers[0].leader_offsets == ((-10, -15),)


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("action", ["MOVE", "COPY"])
@pytest.mark.parametrize("sync", [True, False])
def test_annotation_transform_does_not_edit_hidden_layer_after_start(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str, action: str, sync: bool
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    if owner == "frame":
        item = FeatureControlFrame(
            uuid4().hex, (ToleranceRow("position", 0.1, 2),), (20, 20), layer_name="GDT"
        )
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [item.to_mapping()]})
        identity = item.frame_id
    else:
        item = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), layer_name="GDT")
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [item.to_mapping()]})
        identity = item.datum_id
    tools.selected_kind, tools.selected_id, tools.selected_ids = owner, identity, {identity}
    assert tools.handle_command(action)
    assert tools.handle_command("0,0")
    hidden = replace(
        layers,
        layers=tuple(
            replace(layer, visible=False) if layer.name == "GDT" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": hidden.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    if sync:
        cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    count = loaded.document.command_count
    assert tools.handle_command("5,0")
    assert loaded.document.command_count == count
    assert "隐藏" in editor.canvas.message
    assert services.kernel.drawing_tolerance_frames == ((item,) if owner == "frame" else ())
    assert services.kernel.drawing_datum_identifiers == ((item,) if owner == "datum" else ())
    assert tools.transform_action == action.lower()
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    assert tools.handle_command("5,0")
    items = (
        services.kernel.drawing_tolerance_frames
        if owner == "frame"
        else services.kernel.drawing_datum_identifiers
    )
    assert len(items) == (2 if action == "COPY" else 1)
    assert any(candidate.position_mm == (25, 20) for candidate in items)


def test_reference_dimension_move_does_not_edit_hidden_layer_after_start(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    dimension = DetachedDimension(
        uuid4().hex, "rotated", (0, 0), (20, 0), (10, 5), 0, 20, layer_name="GDT"
    )
    assert tools.execute("drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]})
    tools.selected_kind = "reference"
    tools.selected_id = dimension.dimension_id
    tools.selected_ids = {dimension.dimension_id}
    assert tools.handle_command("MOVE") and tools.handle_command("0,0")
    hidden = replace(
        layers,
        layers=tuple(
            replace(layer, visible=False) if layer.name == "GDT" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": hidden.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    count = loaded.document.command_count
    assert tools.handle_command("5,0")
    assert loaded.document.command_count == count
    assert services.kernel.drawing_reference_dimensions == (dimension,)
    assert "隐藏" in editor.canvas.message


@pytest.mark.parametrize("action", ["MOVE", "COPY"])
@pytest.mark.parametrize("external", [False, True])
def test_single_frame_transform_rejects_changed_source(
    qtbot: QtBot, action: str, external: bool
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (20, 20))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_kind, tools.selected_id, tools.selected_ids = (
        "frame",
        frame.frame_id,
        {frame.frame_id},
    )
    assert tools.handle_command(action) and tools.handle_command("0,0")
    modified = replace(frame, position_mm=(30, 20))
    if external:
        loaded.bus.execute(
            "drawing.tolerance.batch", {"update_frames": [modified.to_mapping()]}, "local"
        )
    else:
        assert tools.execute("drawing.tolerance.batch", {"update_frames": [modified.to_mapping()]})
    count = loaded.document.command_count
    assert tools.handle_command("5,0")
    assert loaded.document.command_count == count
    assert services.kernel.drawing_tolerance_frames == (modified,)
    assert "改变" in editor.canvas.message


@pytest.mark.parametrize("owner", ["datum", "reference"])
@pytest.mark.parametrize("external", [False, True])
def test_single_annotation_move_rejects_changed_source(
    qtbot: QtBot, owner: str, external: bool
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    update: dict[str, object]
    if owner == "datum":
        item = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0))
        changed = replace(item, position_mm=(30, 20))
        command = "drawing.tolerance.batch"
        assert tools.execute(command, {"add_datums": [item.to_mapping()]})
        update = {"update_datums": [changed.to_mapping()]}
        identity = item.datum_id
    else:
        item = DetachedDimension(uuid4().hex, "rotated", (0, 0), (20, 0), (10, 5), 0, 20)
        changed = replace(item, location_mm=(10, 8))
        command = "drawing.reference_dimensions.batch"
        assert tools.execute(command, {"add": [item.to_mapping()]})
        update = {"update": [changed.to_mapping()]}
        identity = item.dimension_id
    tools.selected_kind, tools.selected_id, tools.selected_ids = owner, identity, {identity}
    assert tools.handle_command("MOVE") and tools.handle_command("0,0")
    if external:
        loaded.bus.execute(command, update, "local")
    else:
        assert tools.execute(command, update)
    count = loaded.document.command_count
    assert tools.handle_command("5,0")
    assert loaded.document.command_count == count
    assert "改变" in editor.canvas.message
    if owner == "datum":
        assert services.kernel.drawing_datum_identifiers == (changed,)
    else:
        assert services.kernel.drawing_reference_dimensions == (changed,)


def test_datum_copy_rejects_source_changed_while_name_dialog_open(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0))
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    tools.selected_kind, tools.selected_id, tools.selected_ids = (
        "datum",
        datum.datum_id,
        {datum.datum_id},
    )
    assert tools.handle_command("COPY") and tools.handle_command("0,0")
    changed = replace(datum, position_mm=(30, 20))

    def change_during_dialog(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        loaded.bus.execute(
            "drawing.tolerance.batch", {"update_datums": [changed.to_mapping()]}, "local"
        )
        return "B", True

    monkeypatch.setattr(QInputDialog, "getText", change_during_dialog)
    assert tools.handle_command("5,0")
    assert services.kernel.drawing_datum_identifiers == (changed,)
    assert "改变" in editor.canvas.message


def test_datum_copy_rejects_layer_hidden_while_name_dialog_open(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), layer_name="GDT")
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    tools.selected_kind, tools.selected_id, tools.selected_ids = (
        "datum",
        datum.datum_id,
        {datum.datum_id},
    )
    assert tools.handle_command("COPY") and tools.handle_command("0,0")

    def hide_during_dialog(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        hidden = replace(
            layers,
            layers=tuple(
                replace(layer, visible=False) if layer.name == "GDT" else layer
                for layer in layers.layers
            ),
        )
        loaded.bus.execute(
            "drawing.layers.set", {"layers": hidden.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
        return "B", True

    monkeypatch.setattr(QInputDialog, "getText", hide_during_dialog)
    assert tools.handle_command("5,0")
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert "隐藏" in editor.canvas.message


@pytest.mark.parametrize("owner", ["datum", "frame", "reference"])
def test_annotation_dialog_rejects_unsynchronized_source_change(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    if owner == "frame":
        item = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (20, 20))
        changed = replace(item, position_mm=(30, 20))
        command = "drawing.tolerance.batch"
        assert tools.execute(command, {"add_frames": [item.to_mapping()]})
        update = {"update_frames": [changed.to_mapping()]}
        point = tools.screen_bounds(item).center().toPoint()
    elif owner == "datum":
        item = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0))
        changed = replace(item, position_mm=(30, 20))
        command = "drawing.tolerance.batch"
        assert tools.execute(command, {"add_datums": [item.to_mapping()]})
        update = {"update_datums": [changed.to_mapping()]}
        point = tools.datum_screen_bounds(item).center().toPoint()
    else:
        item = DetachedDimension(uuid4().hex, "rotated", (0, 0), (20, 0), (10, 5), 0, 20)
        changed = replace(item, location_mm=(10, 8))
        command = "drawing.reference_dimensions.batch"
        assert tools.execute(command, {"add": [item.to_mapping()]})
        update = {"update": [changed.to_mapping()]}
        point = tools.reference_bounds(item).center().toPoint()

    def modify() -> None:
        loaded.bus.execute(command, update, "local")

    def answer(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        modify()
        return "B", True

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QDialog)
        modify()
        dialog.accept()

    if owner == "datum":
        monkeypatch.setattr(QInputDialog, "getText", answer)
    else:
        QTimer.singleShot(20, accept)
    editor.canvas.set_tool("选择元素")
    QTest.mouseDClick(editor.canvas, Qt.MouseButton.LeftButton, pos=point)
    assert "改变" in editor.canvas.message
    if owner == "frame":
        assert services.kernel.drawing_tolerance_frames == (changed,)
    elif owner == "datum":
        assert services.kernel.drawing_datum_identifiers == (changed,)
    else:
        assert services.kernel.drawing_reference_dimensions == (changed,)


@pytest.mark.parametrize("case", ["source_hidden", "destination_hidden"])
def test_frame_dialog_rejects_hidden_layer(qtbot: QtBot, case: str) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    layers = layers.add(SketchLayer("HIDDEN", visible=False))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2),), (20, 20), layer_name="GDT"
    )
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    point = tools.screen_bounds(frame).center().toPoint()

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        if case == "source_hidden":
            hidden = replace(
                layers,
                layers=tuple(
                    replace(layer, visible=False) if layer.name == "GDT" else layer
                    for layer in layers.layers
                ),
            )
            loaded.bus.execute(
                "drawing.layers.set",
                {"layers": hidden.to_mapping(), "dimension_layer": "DIM"},
                "local",
            )
        else:
            dialog.layer.setCurrentText("HIDDEN")
        dialog.accept()

    editor.canvas.set_tool("选择元素")
    QTimer.singleShot(20, accept)
    QTest.mouseDClick(editor.canvas, Qt.MouseButton.LeftButton, pos=point)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert "隐藏" in editor.canvas.message


@pytest.mark.parametrize("owner", ["datum", "frame", "reference"])
def test_delete_selected_annotation_rejects_unsynchronized_hidden_layer(
    qtbot: QtBot, owner: str
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    if owner == "frame":
        item = FeatureControlFrame(
            uuid4().hex, (ToleranceRow("position", 0.1, 2),), (20, 20), layer_name="GDT"
        )
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [item.to_mapping()]})
        point = tools.screen_bounds(item).center().toPoint()
        identity = item.frame_id
    elif owner == "datum":
        item = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), layer_name="GDT")
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [item.to_mapping()]})
        point = tools.datum_screen_bounds(item).center().toPoint()
        identity = item.datum_id
    else:
        item = DetachedDimension(
            uuid4().hex, "rotated", (0, 0), (20, 0), (10, 5), 0, 20, layer_name="GDT"
        )
        assert tools.execute("drawing.reference_dimensions.batch", {"add": [item.to_mapping()]})
        point = tools.reference_bounds(item).center().toPoint()
        identity = item.dimension_id
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    assert tools.selected_id == identity
    hidden = replace(
        layers,
        layers=tuple(
            replace(layer, visible=False) if layer.name == "GDT" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": hidden.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    count = loaded.document.command_count
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert loaded.document.command_count == count
    assert "隐藏" in canvas.message
    if owner == "frame":
        assert services.kernel.drawing_tolerance_frames == (item,)
    elif owner == "datum":
        assert services.kernel.drawing_datum_identifiers == (item,)
    else:
        assert services.kernel.drawing_reference_dimensions == (item,)


def test_delete_mixed_annotations_is_atomic_when_one_layer_hidden(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (20, 20))
    datum = DatumIdentifier(uuid4().hex, "A", (0, 20), (0, 0), layer_name="GDT")
    assert tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id, datum.datum_id}
    hidden = replace(
        layers,
        layers=tuple(
            replace(layer, visible=False) if layer.name == "GDT" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": hidden.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    count = loaded.document.command_count
    assert tools.delete_selected()
    assert loaded.document.command_count == count
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert "隐藏" in editor.canvas.message


@pytest.mark.parametrize("state", ["hidden", "modified"])
def test_delete_frame_and_text_is_atomic_when_text_layer_hidden(qtbot: QtBot, state: str) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("NOTES"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    tools, text_tools = editor.canvas.geometric_tolerance_tools, editor.canvas.text_tools
    assert tools is not None and tools.execute is not None and text_tools is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (20, 20))
    note = DrawingText(uuid4().hex, "note", (0, 0), layer_name="NOTES")
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute(
        "drawing.text.batch", {"add": [note.to_mapping()], "update": [], "remove": []}
    )
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    text_tools.selected_ids = {note.text_id}
    if state == "hidden":
        hidden = replace(
            layers,
            layers=tuple(
                replace(layer, visible=False) if layer.name == "NOTES" else layer
                for layer in layers.layers
            ),
        )
        loaded.bus.execute(
            "drawing.layers.set", {"layers": hidden.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
        expected = note
    else:
        expected = replace(note, text="changed")
        loaded.bus.execute(
            "drawing.text.batch",
            {"add": [], "update": [expected.to_mapping()], "remove": []},
            "local",
        )
    count = loaded.document.command_count
    assert tools.delete_selected()
    assert loaded.document.command_count == count
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_texts == (expected,)
    assert ("隐藏" if state == "hidden" else "改变") in editor.canvas.message


def test_delete_selected_frame_rejects_unsynchronized_change(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (20, 20))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    changed = replace(frame, position_mm=(30, 20))
    loaded.bus.execute(
        "drawing.tolerance.batch", {"update_frames": [changed.to_mapping()]}, "local"
    )
    count = loaded.document.command_count
    assert tools.delete_selected()
    assert loaded.document.command_count == count
    assert services.kernel.drawing_tolerance_frames == (changed,)
    assert "改变" in editor.canvas.message


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_leader_grip_checks_reference_landing(owner: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, SurfaceIndication

    surface = SurfaceIndication((0, 10), (10, 10), 0.5)
    if owner == "frame":
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (20, 20),
            leader_target_mm=(0, 0),
            leader_offsets=((-15, -10),),
            surface_indication=surface,
        )
    else:
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (20, 20),
            (0, 0),
            leader_offsets=((-15, -10),),
            surface_indication=surface,
        )
    assert _leader_target_overlap(item)
    assert _leader_vertex_overlap(item, 0, (5, 10))
    assert not _leader_vertex_overlap(item, 0, (0, 0))


@pytest.mark.parametrize("focus", ["command", "canvas"])
@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_leader_enter_places_at_last_vertex(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str, focus: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    bar = editor.drawing_command_bar.input
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    assert tools.handle_command("AMDATUMID" if owner == "datum" else "AMFCFRAME")
    for text in ("0,0", "V", "0,10", "V", "20,10"):
        assert tools.handle_command(text)

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    bar.clear()
    if focus == "canvas":
        window.activateWindow()
        editor.canvas.setFocus()
        qtbot.waitUntil(lambda: QApplication.focusWidget() is editor.canvas, timeout=5000)
    if owner == "frame":
        QTimer.singleShot(20, accept)
    QTest.keyClick(bar if focus == "command" else editor.canvas, Qt.Key.Key_Return)
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert len(items) == 1
    assert items[0].position_mm == (20, 10)
    assert items[0].leader_offsets == ((-20, 0),)
    assert not tools.pending
    unit = window.execution_unit
    assert unit is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    remaining = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert not remaining


@pytest.mark.parametrize("focus", ["direct", "canvas"])
@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_leader_enter_keeps_single_normal_vertex(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path, owner: str, focus: str
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    editor.canvas.set_orthogonal_enabled(True)
    assert tools.handle_command("AMDATUMID" if owner == "datum" else "AMFCFRAME")
    for text in ("10,0", "V", "10,10"):
        assert tools.handle_command(text)

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    if focus == "canvas":
        window.show()
        window.activateWindow()
        editor.canvas.setFocus()
        qtbot.waitUntil(lambda: QApplication.focusWidget() is editor.canvas, timeout=5000)
    if owner == "frame":
        QTimer.singleShot(20, accept)
    if focus == "canvas":
        QTest.keyClick(editor.canvas, Qt.Key.Key_Return)
    else:
        assert tools.handle_command("")
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert len(items) == 1
    item = items[0]
    assert item.leader_auto_normal
    assert item.leader_offsets and item.position_mm[0] + item.leader_offsets[-1][
        0
    ] == pytest.approx(10)
    assert item.leader_offsets[-1][1] < 0
    assert not tools.pending
    assert isinstance(item, DatumIdentifier) == (owner == "datum")
    path = (
        tools.datum_screen_path(item)[0]
        if isinstance(item, DatumIdentifier)
        else tools.frame_screen_leader(item)
    )
    assert len(path) in (2, 3)
    assert path[-2].x() == pytest.approx(path[-1].x(), abs=0.1)
    output = tmp_path / f"enter-normal-{owner}.dxf"
    write_sketches_dxf(
        services.kernel.sketches,
        output,
        datum_identifiers=services.kernel.drawing_datum_identifiers,
        tolerance_frames=services.kernel.drawing_tolerance_frames,
    )
    imported = read_sketch_dxf(output)
    restored = imported.datum_identifiers if owner == "datum" else imported.tolerance_frames
    assert restored == (item,)
    attachment = item.attachment if isinstance(item, DatumIdentifier) else item.leader_attachment
    assert attachment is not None
    current = next(s for s in services.kernel.sketches if s.sketch_id == attachment.sketch_id)
    rotated = replace(line, start_mm=(10, -10), end_mm=(10, 10))
    state = replace(current, entities=(rotated,)).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": current.sketch_id,
                    "base_state_sha256": current.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=56,
    )
    changed = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )[0]
    assert changed.leader_auto_normal
    assert isinstance(changed, DatumIdentifier) == (owner == "datum")
    target = changed.target_mm if isinstance(changed, DatumIdentifier) else changed.leader_target_mm
    assert target is not None
    vertex = (
        changed.position_mm[0] + changed.leader_offsets[-1][0],
        changed.position_mm[1] + changed.leader_offsets[-1][1],
    )
    assert vertex[1] == pytest.approx(target[1])
    assert abs(vertex[0] - target[0]) == pytest.approx(
        abs(item.position_mm[1] + item.leader_offsets[-1][1])
    )
    loaded.bus.undo_operation()
    assert (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    ) == (item,)
    loaded.bus.redo_operation()
    assert (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    ) == (changed,)
    saved = tmp_path / f"enter-normal-{owner}.my2d"
    save_document(loaded.document, saved)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, saved)
    assert (
        reopened.kernel.drawing_datum_identifiers
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames
    ) == (changed,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_leader_enter_normal_on_sloped_line(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 20))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    editor.canvas.set_orthogonal_enabled(True)
    assert tools.handle_command("AMDATUMID" if owner == "datum" else "AMFCFRAME")
    for text in ("10,10", "V", "0,20"):
        assert tools.handle_command(text)
    if owner == "frame":

        def accept() -> None:
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, GeometricToleranceDialog)
            dialog.accept()

        QTimer.singleShot(20, accept)
    assert tools.handle_command("")
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert len(items) == 1 and items[0].leader_auto_normal
    assert isinstance(items[0], DatumIdentifier) == (owner == "datum")
    path = (
        tools.datum_screen_path(items[0])[0]
        if isinstance(items[0], DatumIdentifier)
        else tools.frame_screen_leader(items[0])
    )
    assert len(path) >= 2
    segment = path[-2] - path[-1]
    assert segment.x() == pytest.approx(segment.y(), abs=0.1)


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("surface_vertex", [False, True])
@pytest.mark.parametrize("focus", ["direct", "canvas"])
def test_mechanical_leader_enter_surface_normal_preserves_constraint(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    owner: str,
    surface_vertex: bool,
    focus: str,
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    editor.canvas.set_orthogonal_enabled(True)
    assert tools.handle_command("AMDATUMID" if owner == "datum" else "AMFCFRAME")
    for text in ("10,0", "V", "10,10", "F"):
        assert tools.handle_command(text)
    if surface_vertex:
        for text in ("V", "10,5"):
            assert tools.handle_command(text)
    assert tools.handle_command("20,20")

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    if focus == "canvas":
        window.activateWindow()
        editor.canvas.setFocus()
        qtbot.waitUntil(lambda: QApplication.focusWidget() is editor.canvas, timeout=5000)
    if owner == "frame":
        QTimer.singleShot(20, accept)
    if focus == "canvas":
        QTest.keyClick(editor.canvas, Qt.Key.Key_Return)
    else:
        assert tools.handle_command("")
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert len(items) == 1 and not tools.pending
    assert items[0].surface_indication is not None and items[0].surface_indication.auto_normal
    assert items[0].surface_indication.leader_offsets_mm == ((0, 5 if surface_vertex else 10),)
    assert not items[0].leader_auto_normal and not items[0].leader_offsets
    original = items[0]
    path = tmp_path / f"surface-{owner}-{surface_vertex}.dxf"
    write_sketches_dxf(
        services.kernel.sketches,
        path,
        datum_identifiers=services.kernel.drawing_datum_identifiers,
        tolerance_frames=services.kernel.drawing_tolerance_frames,
    )
    result = read_sketch_dxf(path)
    assert (result.datum_identifiers if owner == "datum" else result.tolerance_frames) == (
        original,
    )
    current = next(
        s
        for s in services.kernel.sketches
        if s.entities and s.entities[0].entity_id == line.entity_id
    )
    rotated = replace(line, start_mm=(10, -10), end_mm=(10, 10))
    state = replace(current, entities=(rotated,)).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": current.sketch_id,
                    "base_state_sha256": current.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=56,
    )
    changed = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )[0]
    assert changed.surface_indication is not None and changed.surface_indication.auto_normal
    offset = changed.surface_indication.leader_offsets_mm[0]
    assert offset[1] == pytest.approx(0)
    assert abs(offset[0]) == pytest.approx(5 if surface_vertex else 10)
    loaded.bus.undo_operation()
    assert (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    ) == (original,)
    loaded.bus.redo_operation()
    saved = tmp_path / f"surface-{owner}-{surface_vertex}.my2d"
    save_document(loaded.document, saved)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, saved)
    assert (
        reopened.kernel.drawing_datum_identifiers
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames
    ) == (changed,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_leader_enter_dialog_cancel_discards_placement(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    count = loaded.document.command_count
    assert tools.handle_command("AMDATUMID" if owner == "datum" else "AMFCFRAME")
    for text in ("0,0", "V", "0,10", "V", "20,10"):
        assert tools.handle_command(text)
    if owner == "datum":
        monkeypatch.setattr(QInputDialog, "getText", _text_response("", accepted=False))
    else:

        def reject() -> None:
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, GeometricToleranceDialog)
            dialog.reject()

        QTimer.singleShot(20, reject)
    assert tools.handle_command("")
    assert not tools.pending and loaded.document.command_count == count


def test_mechanical_datum_preview_tracks_pointer(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    tools.begin_mechanical_datum()
    assert tools.handle_command("0,0")
    first_pointer = canvas.rect().center()
    second_pointer = first_pointer + QPointF(20, 0).toPoint()
    QTest.mouseMove(canvas, first_pointer)
    qtbot.wait(20)
    assert tools.mechanical_datum_preview is not None
    assert tools.mechanical_datum_preview.position_mm == pytest.approx(
        canvas.screen_to_local(QPointF(first_pointer))
    )
    assert tools.mechanical_datum_preview.target_mm == pytest.approx((0, 0))
    drawing = QImage(canvas.size(), QImage.Format.Format_ARGB32)
    drawing.fill(Qt.GlobalColor.transparent)
    painter = QPainter(drawing)
    tools.draw(painter)
    painter.end()
    preview_bounds = tools.datum_screen_bounds(tools.mechanical_datum_preview)
    assert any(
        drawing.pixelColor(x, y).alpha() > 0
        for x in range(int(preview_bounds.left()), int(preview_bounds.right()) + 1)
        for y in range(int(preview_bounds.top()), int(preview_bounds.bottom()) + 1)
    )
    before = canvas.grab().toImage()
    QTest.mouseMove(canvas, second_pointer)
    qtbot.wait(20)
    assert tools.mechanical_datum_preview is not None
    assert tools.mechanical_datum_preview.position_mm == pytest.approx(
        canvas.screen_to_local(QPointF(second_pointer))
    )
    assert canvas.grab().toImage() != before
    assert not services.kernel.drawing_datum_identifiers
    assert tools.cancel()


def test_mechanical_datum_attaches_and_undoes(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    editor = window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (1, 2), (15, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_mechanical_datum()
    assert tools.handle_command("1,2")
    assert tools.handle_command("3,10")
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.attachment is not None
    assert datum.attachment.sketch_id == sketch.sketch_id
    assert datum.attachment.reference.entity_id == line.entity_id
    window.request_undo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_datum_identifiers, timeout=10000)


def test_tolerance_toolbar_actions_visible_in_compact_layout(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    toolbar = editor.dimension_toolbar
    toolbar.setMaximumWidth(300)
    qtbot.wait(50)
    for action in (window.act_geometric_tolerance, window.act_datum_label):
        button = toolbar.widgetForAction(action)
        assert button is not None and button.isVisible()
        from PySide6.QtWidgets import QToolButton

        assert isinstance(button, QToolButton)
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon
    editor.set_compact_layout(True)
    qtbot.wait(50)
    for action in (window.act_geometric_tolerance, window.act_datum_label):
        button = toolbar.widgetForAction(action)
        assert isinstance(button, QToolButton) and button.isVisible()
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    editor.set_compact_layout(False)
    qtbot.wait(50)
    for action in (window.act_geometric_tolerance, window.act_datum_label):
        button = toolbar.widgetForAction(action)
        assert isinstance(button, QToolButton) and button.isVisible()
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon


def test_tolerance_toolbar_uses_shared_icon_actions(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    actions = editor.dimension_toolbar.actions()
    assert window.act_geometric_tolerance in actions
    assert window.act_datum_label in actions
    assert not window.act_geometric_tolerance.icon().isNull()
    assert not window.act_datum_label.icon().isNull()
    assert not any(action.text() == "修复标注身份" for action in editor.drawing_toolbar.actions())
    cast("Callable[..., None]", _private_member(window, "_on_theme_action"))("light")
    light_icons = tuple(
        action.icon().pixmap(QSize(24, 24)).toImage()
        for action in (window.act_datum_label, window.act_geometric_tolerance)
    )
    cast("Callable[..., None]", _private_member(window, "_on_theme_action"))("dark")
    dark_icons = tuple(
        action.icon().pixmap(QSize(24, 24)).toImage()
        for action in (window.act_datum_label, window.act_geometric_tolerance)
    )
    assert all(light != dark for light, dark in zip(light_icons, dark_icons, strict=True))
    window.act_datum_label.trigger()
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.mechanical_datum_active
    assert tools.cancel()
    window.act_geometric_tolerance.trigger()
    assert tools.mechanical_frame_active
    assert tools.cancel()


def test_frame_leader_draws_and_can_be_selected(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (0, 0),
        leader_target_mm=(20, -15),
        leader_offsets=((10, -15),),
    )
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    canvas.set_tool("选择元素")
    path = tools.frame_screen_leader(frame)
    assert len(path) == 3
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=((path[-1] + path[-2]) / 2).toPoint())
    assert tools.selected_id == frame.frame_id
    assert tools.handle_command("MOVE")
    assert tools.handle_command("0,0")
    assert tools.handle_command("5,2")
    changed = services.kernel.drawing_tolerance_frames[0]
    assert changed.position_mm == (5, 2)
    assert changed.leader_target_mm == (25, -13)


@pytest.mark.parametrize("selection", ["click", "crossing"])
@pytest.mark.parametrize("arrow_style", ["legacy", "closed_filled"])
def test_frame_primary_arrow_can_be_selected(
    qtbot: QtBot, selection: str, arrow_style: str
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import SurfaceIndication
    from mycad.core.geometric_tolerance_geometry import datum_triangle, frame_leader_arrow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas, tools = editor.canvas, editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (0, 40),
        leader_target_mm=(0, -10),
        leader_anchor_offset=(0, -10),
        surface_indication=SurfaceIndication((-5, 10), (5, 10), 0.5, arrow_size_mm=20),
        leader_arrow_style=arrow_style,
    )
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    points = tools.frame_screen_leader(frame)
    triangle = (datum_triangle if arrow_style == "legacy" else frame_leader_arrow)(
        (points[-2].x(), points[-2].y()),
        (points[-1].x(), points[-1].y()),
        20 * canvas.view_scale,
    )
    tip, corner = QPointF(*triangle[0]), QPointF(*triangle[1])
    point = tip * 0.1 + corner * 0.9
    canvas.set_tool("选择元素")
    if selection == "click":
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point.toPoint())
    else:
        tools.select_box(
            point + QPointF(2, -2), point + QPointF(-2, 2), Qt.KeyboardModifier.NoModifier
        )
    assert tools.selected_id == frame.frame_id


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_crossing_selection_ignores_empty_space_inside_bent_leader(
    qtbot: QtBot, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas, tools = editor.canvas, editor.canvas.geometric_tolerance_tools
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (30, -35), leader_offsets=((30, -5),))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (0, 0),
        leader_target_mm=(30, -35),
        leader_offsets=((30, -5),),
        leader_anchor_offset=(0, -5),
    )
    params: dict[str, object] = (
        {"add_datums": [datum.to_mapping()]}
        if owner == "datum"
        else {"add_frames": [frame.to_mapping()]}
    )
    assert tools.execute is not None and tools.execute("drawing.tolerance.batch", params)
    point = canvas.local_to_screen_precise((20, -15))
    tools.select_box(point + QPointF(2, -2), point + QPointF(-2, 2), Qt.KeyboardModifier.NoModifier)
    assert not tools.selected_ids


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_crossing_selection_ignores_empty_space_inside_surface_leader(
    qtbot: QtBot, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, SurfaceIndication

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas, tools = editor.canvas, editor.canvas.geometric_tolerance_tools
    indication = SurfaceIndication((30, 30), (40, 30), 0.5, ((30, 0),))
    datum = DatumIdentifier(uuid4().hex, "A", (50, 50), (0, 0), surface_indication=indication)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (50, 50),
        leader_target_mm=(0, 0),
        surface_indication=indication,
    )
    params: dict[str, object] = (
        {"add_datums": [datum.to_mapping()]}
        if owner == "datum"
        else {"add_frames": [frame.to_mapping()]}
    )
    assert tools.execute is not None and tools.execute("drawing.tolerance.batch", params)
    point = canvas.local_to_screen_precise((20, 10))
    tools.select_box(point + QPointF(2, -2), point + QPointF(-2, 2), Qt.KeyboardModifier.NoModifier)
    assert not tools.selected_ids


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("selection", ["click", "crossing"])
def test_surface_indication_arrow_interior_can_be_clicked(
    qtbot: QtBot, owner: str, selection: str
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, SurfaceIndication
    from mycad.core.geometric_tolerance_geometry import datum_triangle

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas, tools = editor.canvas, editor.canvas.geometric_tolerance_tools
    indication = SurfaceIndication((30, 30), (40, 30), 0.5, arrow_size_mm=20)
    datum = DatumIdentifier(uuid4().hex, "A", (40, 40), (0, 0), surface_indication=indication)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (40, 40),
        leader_target_mm=(0, 0),
        surface_indication=indication,
    )
    params: dict[str, object] = (
        {"add_datums": [datum.to_mapping()]}
        if owner == "datum"
        else {"add_frames": [frame.to_mapping()]}
    )
    assert tools.execute is not None and tools.execute("drawing.tolerance.batch", params)
    _, leader, _ = tools.surface_indication_screen_geometry((0, 0), indication)
    triangle = datum_triangle(
        (leader[-2].x(), leader[-2].y()), (leader[-1].x(), leader[-1].y()), 20 * canvas.view_scale
    )
    point = (
        QPointF(*triangle[0]) * 0.15 + QPointF(*triangle[1]) * 0.7 + QPointF(*triangle[2]) * 0.15
    )
    canvas.set_tool("选择元素")
    if selection == "click":
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point.toPoint())
    else:
        tools.select_box(
            point + QPointF(2, -2), point + QPointF(-2, 2), Qt.KeyboardModifier.NoModifier
        )
    assert tools.selected_id == (datum.datum_id if owner == "datum" else frame.frame_id)


def test_frame_leader_vertex_grip_is_undoable(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas, tools = editor.canvas, editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (0, 0),
        leader_target_mm=(20, -15),
        leader_offsets=((10, -15),),
        leader_anchor_offset=(5, -6),
    )
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, -15)))
    assert tools.selected_id == frame.frame_id
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, -15)))
    assert tools.handle_command("12,-12")
    assert services.kernel.drawing_tolerance_frames[0].leader_offsets == ((12, -12),)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_tolerance_frames == (frame,), timeout=10000)


def test_frame_leader_target_grip_rejects_invalid_reattach(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas, tools = editor.canvas, editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.begin_mechanical_frame()
    assert tools.handle_command("10,0")

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    assert tools.handle_command("20,20")
    frame = services.kernel.drawing_tolerance_frames[0]
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert frame.leader_target_mm is not None
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(frame.leader_target_mm)
    )
    assert tools.handle_command("100,100")
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert "唯一" in editor.status_label.text()
    assert tools.handle_command("5,0")
    assert services.kernel.drawing_tolerance_frames[0].leader_target_mm == pytest.approx((5, 0))


def test_frame_create_place_select_delete_undo(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.rows[0].characteristic.setCurrentIndex(
            dialog.rows[0].characteristic.findData("position")
        )
        dialog.rows[0].value.setValue(0.05)
        dialog.rows[0].datums[0].setText("A")
        dialog.accept()

    QTimer.singleShot(20, accept)
    tools.begin_frame()
    point = editor.canvas.local_to_screen((10, 10))
    QTest.mouseClick(editor.canvas, Qt.MouseButton.LeftButton, pos=point)
    assert len(services.kernel.drawing_tolerance_frames) == 1
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.rows[0].characteristic == "position"
    bounds = tools.screen_bounds(frame)
    editor.canvas.selected_entity_ids = {"stale-geometry-selection"}
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=QPointF(bounds.center()).toPoint()
    )
    assert tools.selected_id == frame.frame_id
    assert window.act_delete.isEnabled()
    assert not editor.canvas.selected_entity_ids
    assert tools.delete_selected()
    assert not services.kernel.drawing_tolerance_frames
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_tolerance_frames == (frame,), timeout=10000)
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_mechanical_frame_placement_and_cancel(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools.handle_command("AMFCFRAME")
    assert tools.handle_command("0,0")
    assert tools.handle_command("V")
    assert tools.handle_command("5,5")

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    assert tools.handle_command("10,10")
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.position_mm == (10, 10)
    assert frame.leader_target_mm == (0, 0)
    assert frame.leader_offsets == ((-5, -5),)
    assert frame.leader_anchor_offset is not None
    assert not tools.pending
    assert tools.handle_command("AMFCFRAME")
    assert tools.handle_command("1,2")
    assert tools.cancel()
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_mechanical_frame_attaches_to_line(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.begin_mechanical_frame()
    assert tools.handle_command("10,0")
    assert tools.mechanical_frame_attachment is not None

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    assert tools.handle_command("20,20")
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.leader_attachment is not None
    assert frame.leader_attachment.reference.entity_id == line.entity_id


def test_pick_ellipse_annotation_attachment(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import EllipseEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    ellipse = EllipseEntity(uuid4().hex, (0, 0), 30, 15, rotation_deg=20)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (ellipse,))
    editor.canvas.associative_sketches_provider = lambda: (sketch,)
    attachment, point = cast(
        "Callable[..., tuple[DatumAttachment | None, tuple[float, float]]]",
        _private_member(editor.canvas.geometric_tolerance_tools, "_pick_attachment"),
    )(ellipse.point_at(0.125))
    assert attachment is not None and attachment.curve_kind == "ellipse"
    assert attachment.parameter == pytest.approx(0.125, abs=1e-6)
    assert point == pytest.approx(ellipse.point_at(0.125), abs=1e-5)


def test_ellipse_attachment_finds_seam_and_detects_ambiguous_points() -> None:
    from uuid import uuid4

    import mycad.ui.geometric_tolerance_tools as tolerance_tools_module
    from mycad.core.sketch import EllipseEntity

    ellipse_hits = cast(
        "Callable[[EllipseEntity, tuple[float, float], float], tuple[tuple[float, tuple[float, float]], ...]]",
        vars(tolerance_tools_module)["_ellipse_hits"],
    )

    ellipse = EllipseEntity(uuid4().hex, (0, 0), 10, 5)
    seam = ellipse_hits(ellipse, (10, 0), 0.01)
    assert len(seam) == 1
    assert seam[0][1] == pytest.approx((10, 0), abs=1e-7)
    ambiguous = ellipse_hits(ellipse, (0, 0), 5.1)
    assert len(ambiguous) == 2
    arc = EllipseEntity(uuid4().hex, (0, 0), 10, 5, sweep_angle_deg=-90)
    assert ellipse_hits(arc, (0, 5), 0.1) == ()
    assert len(ellipse_hits(arc, (0, -5), 0.1)) == 1


def test_frame_reports_missing_leader_attachment(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (0, 0),
        leader_target_mm=(20, -15),
        leader_anchor_offset=(5, -6),
        leader_attachment=DatumAttachment(
            uuid4().hex, SketchGeometryReference(uuid4().hex, "start")
        ),
    )
    tools.sync((frame,), ())
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert "失关联" in editor.status_label.text()


def test_frame_edit_reanchors_rotated_leader(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.sync(services.kernel.drawing_tolerance_frames, services.kernel.drawing_datum_identifiers)
    editor.canvas.set_tool("选择元素")

    def edit() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.rotation.setValue(45)
        dialog.accept()

    QTimer.singleShot(20, edit)
    QTest.mouseDClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    updated = services.kernel.drawing_tolerance_frames[0]
    assert updated.rotation_deg == 45
    assert updated.leader_anchor_offset != frame.leader_anchor_offset


def test_frame_leader_anchor_is_independent_of_zoom(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10.3, 10.7),
        23,
        leader_target_mm=(1.2, -2.3),
    )
    vars(editor.canvas)["_scale"] = 3.0
    first = cast(
        "Callable[..., tuple[float, float] | None]", _private_member(tools, "_frame_leader_anchor")
    )(frame)
    vars(editor.canvas)["_scale"] = 16.0
    second = cast(
        "Callable[..., tuple[float, float] | None]", _private_member(tools, "_frame_leader_anchor")
    )(frame)
    assert first is not None and second is not None
    assert first == pytest.approx(second, abs=1e-10)


def test_delete_selected_frame_and_referenced_datum_is_atomic(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (4, 5),
    )
    assert tools.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
    )
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id, datum.datum_id}
    assert tools.delete_selected()
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_datum_identifiers
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_tolerance_frames == (frame,), timeout=10000)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    window.request_redo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_tolerance_frames, timeout=10000)
    assert not services.kernel.drawing_datum_identifiers


def test_multi_delete_does_not_remove_datum_referenced_by_unselected_frame(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    linked = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (4, 5),
    )
    other = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute(
        "drawing.tolerance.batch",
        {
            "add_datums": [datum.to_mapping()],
            "add_frames": [linked.to_mapping(), other.to_mapping()],
        },
    )
    loaded = window.loaded_document()
    assert loaded is not None
    count = loaded.document.command_count
    tools.selected_id, tools.selected_kind = other.frame_id, "frame"
    tools.selected_ids = {other.frame_id, datum.datum_id}
    assert not tools.delete_selected()
    assert services.kernel.drawing_tolerance_frames == (linked, other)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert loaded.document.command_count == count


def test_delete_refuses_mixed_tolerance_and_dimension_selection(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    editor.canvas.selected_constraint_ids = {uuid4().hex}
    assert tools.delete_selected()
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_delete_mixed_reference_dimension_and_tolerance_as_one_undo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    dimension = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute("drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]})
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id, dimension.dimension_id}
    assert tools.delete_selected()
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_reference_dimensions
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_tolerance_frames == (frame,), timeout=10000)
    assert services.kernel.drawing_reference_dimensions == (dimension,)
    window.request_redo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_tolerance_frames, timeout=10000)
    assert not services.kernel.drawing_reference_dimensions


def test_delete_mixed_text_and_tolerance_as_one_undo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import DrawingText

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    text_tools = editor.canvas.text_tools
    assert tools is not None and tools.execute is not None and text_tools is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    text = DrawingText(uuid4().hex, "note", (0, 0))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute(
        "drawing.text.batch", {"add": [text.to_mapping()], "update": [], "remove": []}
    )
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    text_tools.selected_ids = {text.text_id}
    assert tools.delete_selected()
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_texts
    unit = window.execution_unit
    assert unit is not None
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert services.kernel.drawing_texts == (text,)
    window.request_redo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_tolerance_frames, timeout=10000)
    assert not services.kernel.drawing_texts


@pytest.mark.parametrize("operation", ["clipboard", "COPY"])
def test_mixed_text_and_frame_copy_together(qtbot: QtBot, operation: str) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import DrawingText

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools, text_tools = editor.canvas.geometric_tolerance_tools, editor.canvas.text_tools
    assert tools is not None and tools.execute is not None and text_tools is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    note = DrawingText(uuid4().hex, "note", (0, 0))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute(
        "drawing.text.batch", {"add": [note.to_mapping()], "update": [], "remove": []}
    )
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    text_tools.selected_ids = {note.text_id}
    if operation == "clipboard":
        assert editor.canvas.copy_to_clipboard() and editor.canvas.begin_clipboard_paste()
        _place_annotation(tools, "mixed", (15, 8))
    else:
        assert tools.handle_command(operation)
        assert tools.handle_command("0,0") and tools.handle_command("5,3")
    assert len(services.kernel.drawing_tolerance_frames) == 2
    assert len(services.kernel.drawing_texts) == 2
    assert services.kernel.drawing_tolerance_frames[-1].position_mm == (15, 8)
    assert services.kernel.drawing_texts[-1].position_mm == (5, 3)
    assert services.kernel.drawing_texts[-1].text_id != note.text_id
    loaded = window.loaded_document()
    assert loaded is not None
    loaded.bus.undo_operation()
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_texts == (note,)
    loaded.bus.redo_operation()
    assert len(services.kernel.drawing_tolerance_frames) == len(services.kernel.drawing_texts) == 2


@pytest.mark.parametrize("operation", ["clipboard", "COPY", "MOVE"])
def test_mixed_dimension_and_frame_without_geometry_does_not_silently_omit_dimension(
    qtbot: QtBot, operation: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, -10),
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),
        session_identity=0,
    )
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    QApplication.clipboard().setText("existing clipboard")
    if operation == "clipboard":
        assert not editor.canvas.copy_to_clipboard()
    else:
        assert tools.handle_command(operation)
    assert QApplication.clipboard().text() == "existing clipboard"
    assert (
        not tools.transform_action and not tools.mixed_move_active and not tools.mixed_copy_command
    )
    assert "尺寸" in editor.canvas.message


@pytest.mark.parametrize("operation", ["clipboard", "COPY"])
def test_mixed_raster_and_frame_copy_together(qtbot: QtBot, operation: str) -> None:
    import base64
    import struct
    import zlib
    from uuid import uuid4

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_text import DrawingText

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    image = DrawingRaster(uuid4().hex, base64.b64encode(png).decode("ascii"), (0, 0), 1, 1)
    note = DrawingText(uuid4().hex, "note", (0, 10))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute("drawing.raster.add", image.to_mapping(version=2))
    assert tools.execute(
        "drawing.text.batch", {"add": [note.to_mapping()], "update": [], "remove": []}
    )
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    editor.canvas.selected_raster_ids = {image.image_id}
    assert editor.canvas.text_tools is not None
    editor.canvas.text_tools.selected_ids = {note.text_id}
    if operation == "clipboard":
        assert editor.canvas.copy_to_clipboard() and editor.canvas.begin_clipboard_paste()
        _place_annotation(tools, "mixed", (15, 8))
    else:
        assert tools.handle_command(operation)
        assert tools.handle_command("0,0") and tools.handle_command("5,3")
    assert len(services.kernel.drawing_tolerance_frames) == 2
    assert len(services.kernel.drawing_rasters) == 2
    assert services.kernel.drawing_tolerance_frames[-1].position_mm == (15, 8)
    assert services.kernel.drawing_rasters[-1].origin_mm == (5, 3)
    assert services.kernel.drawing_rasters[-1].image_id != image.image_id
    assert len(services.kernel.drawing_texts) == 2
    assert services.kernel.drawing_texts[-1].position_mm == (5, 13)
    loaded = window.loaded_document()
    assert loaded is not None
    loaded.bus.undo_operation()
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_rasters == (image,)
    assert services.kernel.drawing_texts == (note,)
    loaded.bus.redo_operation()
    assert (
        len(services.kernel.drawing_tolerance_frames) == len(services.kernel.drawing_rasters) == 2
    )
    assert len(services.kernel.drawing_texts) == 2


def test_mixed_clipboard_accepts_picture_over_one_megabyte(qtbot: QtBot) -> None:
    import base64
    import struct
    import zlib
    from uuid import uuid4

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.ui.geometric_tolerance_tools import TOLERANCE_CLIPBOARD_MIME

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"tEXt", b"description\0" + b"x" * 800_000)
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    image = DrawingRaster(uuid4().hex, base64.b64encode(png).decode("ascii"), (0, 0), 1, 1)
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute("drawing.raster.add", image.to_mapping(version=2))
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    editor.canvas.selected_raster_ids = {image.image_id}
    assert editor.canvas.copy_to_clipboard()
    mime = QApplication.clipboard().mimeData()
    assert mime is not None and mime.data(TOLERANCE_CLIPBOARD_MIME).size() > 1_000_000
    assert editor.canvas.begin_clipboard_paste()
    _place_annotation(tools, "mixed", (15, 8))
    assert (
        len(services.kernel.drawing_tolerance_frames) == len(services.kernel.drawing_rasters) == 2
    )
    assert services.kernel.drawing_rasters[-1].png_base64 == image.png_base64


def test_mixed_clipboard_size_limit_preserves_document_and_previous_clipboard(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QMimeData

    import mycad.ui.geometric_tolerance_tools as tolerance_tools
    from mycad.core.drawing_text import DrawingText

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools, texts = editor.canvas.geometric_tolerance_tools, editor.canvas.text_tools
    assert tools is not None and tools.execute is not None and texts is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    note = DrawingText(uuid4().hex, "note", (0, 0))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute(
        "drawing.text.batch", {"add": [note.to_mapping()], "update": [], "remove": []}
    )
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    texts.selected_ids = {note.text_id}
    assert editor.canvas.copy_to_clipboard()
    mime = QApplication.clipboard().mimeData()
    assert mime is not None
    payload = bytes(mime.data(tolerance_tools.TOLERANCE_CLIPBOARD_MIME).data())
    monkeypatch.setattr(tolerance_tools, "MAX_MIXED_CLIPBOARD_BYTES", len(payload) - 1)
    QApplication.clipboard().setText("previous")
    assert not editor.canvas.copy_to_clipboard()
    assert QApplication.clipboard().text() == "previous"
    oversized = QMimeData()
    oversized.setData(tolerance_tools.TOLERANCE_CLIPBOARD_MIME, payload)
    QApplication.clipboard().setMimeData(oversized)
    count = loaded.document.command_count
    assert editor.canvas.begin_clipboard_paste()
    assert tools.clipboard_mixed is None and loaded.document.command_count == count
    assert services.kernel.drawing_tolerance_frames == (
        frame,
    ) and services.kernel.drawing_texts == (note,)
    assert "过大" in editor.canvas.message


def test_mixed_clipboard_accepts_prior_payload_without_auxiliary_fields(qtbot: QtBot) -> None:
    import json
    from uuid import uuid4

    from PySide6.QtCore import QMimeData

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.ui.geometric_tolerance_tools import TOLERANCE_CLIPBOARD_MIME

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    styles = TextStyleTable((TextStyle(), TextStyle("inspect", "字体", height_mm=7)))
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local")
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5), text_style_id="inspect"
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    assert editor.canvas.copy_to_clipboard()
    original = QApplication.clipboard().mimeData()
    assert original is not None
    payload = json.loads(bytes(original.data(TOLERANCE_CLIPBOARD_MIME).data()))
    del payload["object"]["texts"], payload["object"]["rasters"]
    mime = QMimeData()
    mime.setData(TOLERANCE_CLIPBOARD_MIME, json.dumps(payload).encode())
    QApplication.clipboard().setMimeData(mime)
    assert editor.canvas.begin_clipboard_paste() and tools.clipboard_mixed is not None
    _place_annotation(tools, "mixed", (15, 8))
    assert len(services.kernel.drawing_tolerance_frames) == 2


@pytest.mark.parametrize("issue", ["style", "image_count"])
def test_mixed_clipboard_rejects_invalid_auxiliary_data(qtbot: QtBot, issue: str) -> None:
    import json
    from uuid import uuid4

    from PySide6.QtCore import QMimeData

    from mycad.core.drawing_text import DrawingText
    from mycad.ui.geometric_tolerance_tools import TOLERANCE_CLIPBOARD_MIME

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools, text_tools = editor.canvas.geometric_tolerance_tools, editor.canvas.text_tools
    assert tools is not None and tools.execute is not None and text_tools is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    note = DrawingText(uuid4().hex, "note", (0, 0))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute(
        "drawing.text.batch", {"add": [note.to_mapping()], "update": [], "remove": []}
    )
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    text_tools.selected_ids = {note.text_id}
    assert editor.canvas.copy_to_clipboard()
    mime = QApplication.clipboard().mimeData()
    assert mime is not None
    payload = json.loads(bytes(mime.data(TOLERANCE_CLIPBOARD_MIME).data()))
    if issue == "style":
        payload["object"]["texts"][0]["style_id"] = "missing"
    else:
        payload["object"]["rasters"] = [{}] * 1001
    altered = QMimeData()
    altered.setData(TOLERANCE_CLIPBOARD_MIME, json.dumps(payload).encode())
    QApplication.clipboard().setMimeData(altered)
    count = loaded.document.command_count
    assert editor.canvas.begin_clipboard_paste()
    assert tools.clipboard_mixed is None and loaded.document.command_count == count
    assert services.kernel.drawing_tolerance_frames == (
        frame,
    ) and services.kernel.drawing_texts == (note,)
    assert "剪贴板数据无效" in editor.canvas.message
    if issue == "image_count":
        assert "1000" in editor.canvas.message


def test_mixed_raster_paste_into_locked_layer_is_atomic(qtbot: QtBot) -> None:
    import base64
    import struct
    import zlib
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.sketch_layers import SketchLayer

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("IMG"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    image = DrawingRaster(
        uuid4().hex, base64.b64encode(png).decode("ascii"), (0, 0), 1, 1, layer_name="IMG"
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    loaded.bus.execute("drawing.raster.add", image.to_mapping(version=2), "local", version=2)
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    editor.canvas.selected_raster_ids = {image.image_id}
    assert editor.canvas.copy_to_clipboard()
    locked = layers.replace(replace(layers.get("IMG"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    sync(window)
    assert editor.canvas.begin_clipboard_paste()
    count = loaded.document.command_count
    _place_annotation(tools, "mixed", (15, 8))
    assert loaded.document.command_count == count
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_rasters == (image,)
    assert "锁定" in editor.canvas.message


@pytest.mark.parametrize("with_image", [False, True])
def test_cross_document_mixed_text_copy_reconciles_style(
    qtbot: QtBot, tmp_path: Path, with_image: bool
) -> None:
    import base64
    import struct
    import zlib
    from uuid import uuid4

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
    from mycad.core.persistence import save_document

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )

    services = app.build_app(discoverers=())
    session = DocumentSession()
    window = MainWindow(services=services, document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    styles = TextStyleTable((TextStyle(), TextStyle("inspect", "字体", "Font A")))
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local")
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5), text_style_id="inspect"
    )
    note = DrawingText(uuid4().hex, "note", (0, 0), style_id="inspect")
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    loaded.bus.execute("drawing.text.batch", {"add": [note.to_mapping()]}, "local")
    image = DrawingRaster(uuid4().hex, base64.b64encode(png).decode("ascii"), (0, 10), 1, 1)
    if with_image:
        loaded.bus.execute("drawing.raster.add", image.to_mapping(version=2), "local", version=2)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools, texts = editor.canvas.geometric_tolerance_tools, editor.canvas.text_tools
    assert tools is not None and texts is not None
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    texts.selected_ids = {note.text_id}
    if with_image:
        editor.canvas.selected_raster_ids = {image.image_id}
    assert editor.canvas.copy_to_clipboard()
    window.act_new_drawing.trigger()
    target, target_loaded = window.active_sketch_dialog(), window.loaded_document()
    assert target is not None and target_loaded is not None and session.active is not None
    kernel = session.active.services.kernel
    destination = TextStyleTable((TextStyle(), TextStyle("inspect", "字体", "Font B")))
    target_loaded.bus.execute("drawing.text_styles.set", destination.to_mapping(), "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    assert target.canvas.begin_clipboard_paste()
    target_tools = target.canvas.geometric_tolerance_tools
    assert target_tools is not None and target_tools.clipboard_mixed is not None
    _place_annotation(target_tools, "mixed", (15, 8))
    assert len(kernel.drawing_tolerance_frames) == len(kernel.drawing_texts) == 1
    copied_frame, copied_note = kernel.drawing_tolerance_frames[0], kernel.drawing_texts[0]
    assert copied_frame.text_style_id == copied_note.style_id != "inspect"
    assert kernel.drawing_text_styles.get(copied_note.style_id).font_family == "Font A"
    assert kernel.drawing_text_styles.get("inspect").font_family == "Font B"
    if with_image:
        assert len(kernel.drawing_rasters) == 1
        assert kernel.drawing_rasters[0].origin_mm == (5, 13)
        assert kernel.drawing_rasters[0].png_base64 == image.png_base64
    target_loaded.bus.undo_operation()
    assert not kernel.drawing_tolerance_frames and not kernel.drawing_texts
    assert not kernel.drawing_rasters
    assert kernel.drawing_text_styles == destination
    target_loaded.bus.redo_operation()
    assert kernel.drawing_tolerance_frames == (copied_frame,) and kernel.drawing_texts == (
        copied_note,
    )
    copied_images = kernel.drawing_rasters
    assert len(copied_images) == int(with_image)
    path = tmp_path / "cross-document-mixed.my2d"
    save_document(target_loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (copied_frame,)
    assert reopened.kernel.drawing_texts == (copied_note,)
    assert reopened.kernel.drawing_rasters == copied_images


def test_move_frame_text_and_raster_is_one_undo(qtbot: QtBot, tmp_path: Path) -> None:
    import base64
    import struct
    import zlib
    from uuid import uuid4

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_text import DrawingText
    from mycad.core.persistence import save_document

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools, texts = editor.canvas.geometric_tolerance_tools, editor.canvas.text_tools
    assert tools is not None and tools.execute is not None and texts is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    note = DrawingText(uuid4().hex, "note", (0, 0))
    raster = DrawingRaster(uuid4().hex, base64.b64encode(png).decode("ascii"), (0, 10), 1, 1)
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute(
        "drawing.text.batch", {"add": [note.to_mapping()], "update": [], "remove": []}
    )
    assert tools.execute("drawing.raster.add", raster.to_mapping(version=2))
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    texts.selected_ids = {note.text_id}
    editor.canvas.selected_raster_ids = {raster.image_id}
    for command in ("MOVE", "0,0", "5,3"):
        assert tools.handle_command(command)
    moved_frame, moved_note, moved_raster = (
        services.kernel.drawing_tolerance_frames[0],
        services.kernel.drawing_texts[0],
        services.kernel.drawing_rasters[0],
    )
    assert moved_frame.position_mm == (15, 8)
    assert moved_note.position_mm == (5, 3)
    assert moved_raster.origin_mm == (5, 13)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_texts == (note,) and services.kernel.drawing_rasters == (raster,)
    loaded.bus.redo_operation()
    path = tmp_path / "mixed-move.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (moved_frame,)
    assert reopened.kernel.drawing_texts == (moved_note,) and reopened.kernel.drawing_rasters == (
        moved_raster,
    )


def test_mixed_move_rejects_document_change_before_commit(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.drawing_text import DrawingText

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools, texts = editor.canvas.geometric_tolerance_tools, editor.canvas.text_tools
    assert tools is not None and tools.execute is not None and texts is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    note = DrawingText(uuid4().hex, "note", (0, 0))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute(
        "drawing.text.batch", {"add": [note.to_mapping()], "update": [], "remove": []}
    )
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    texts.selected_ids = {note.text_id}
    assert tools.handle_command("MOVE") and tools.handle_command("0,0")
    changed = replace(note, text="changed")
    loaded.bus.execute(
        "drawing.text.batch", {"add": [], "update": [changed.to_mapping()], "remove": []}, "local"
    )
    count = loaded.document.command_count
    assert tools.handle_command("5,3")
    assert loaded.document.command_count == count
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_texts == (changed,)
    assert "图纸" in editor.canvas.message and "变化" in editor.canvas.message


def test_delete_mixed_raster_and_tolerance_as_one_undo(qtbot: QtBot) -> None:
    import base64
    import struct
    import zlib
    from uuid import uuid4

    from mycad.core.drawing_raster import DrawingRaster

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    image = DrawingRaster(uuid4().hex, base64.b64encode(png).decode("ascii"), (0, 0), 1, 1)
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute("drawing.raster.add", image.to_mapping(version=2))
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    editor.canvas.selected_raster_ids = {image.image_id}
    assert tools.delete_selected()
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_rasters
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert services.kernel.drawing_rasters == (image,)
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert not services.kernel.drawing_rasters


def test_delete_frame_and_raster_rejects_unsynchronized_raster_change(qtbot: QtBot) -> None:
    import base64
    import struct
    import zlib
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.drawing_raster import DrawingRaster

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    raster = DrawingRaster(uuid4().hex, base64.b64encode(png).decode("ascii"), (0, 0), 1, 1)
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute("drawing.raster.add", raster.to_mapping(version=2))
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    editor.canvas.selected_raster_ids = {raster.image_id}
    changed = replace(raster, origin_mm=(2, 3))
    loaded.bus.execute("drawing.raster.update", changed.to_mapping(version=2), "local", version=3)
    count = loaded.document.command_count
    assert tools.delete_selected()
    assert loaded.document.command_count == count
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_rasters == (changed,)
    assert "图片" in editor.canvas.message and "改变" in editor.canvas.message


def test_mixed_delete_undo_redo_does_not_consume_existing_draft(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.sketch import LineEntity

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    draft = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((draft,))
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    dimension = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute("drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]})
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id, dimension.dimension_id}
    assert tools.delete_selected()
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert tuple(editor.canvas.entities) == (draft,)
    assert services.kernel.drawing_reference_dimensions == (dimension,)
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert tuple(editor.canvas.entities) == (draft,)
    assert not services.kernel.drawing_reference_dimensions


def test_delete_geometry_and_tolerance_together_and_undo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert not services.kernel.sketches[0].entities
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (line,)
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert not services.kernel.sketches[0].entities


def test_mixed_geometry_delete_rolls_back_for_still_referenced_datum(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (4, 5),
    )
    assert tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    count = loaded.document.command_count
    tools.selected_id, tools.selected_kind = datum.datum_id, "datum"
    tools.selected_ids = {datum.datum_id}
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities == (line,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert loaded.document.command_count == count
    assert "失败" in editor.status_label.text()


def test_delete_geometry_and_attached_referenced_datum_together(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, DatumReference
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (1, 2),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (4, 5),
    )
    assert tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id, datum.datum_id}
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert not services.kernel.sketches[0].entities
    assert not services.kernel.drawing_datum_identifiers
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (line,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.datum_attachment_resolved(datum.datum_id)


def test_mixed_geometry_delete_rolls_back_for_locked_frame(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5), layer_name="GDT"
    )
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "GDT" else layer for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    sync(window)
    count = loaded.document.command_count
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities == (line,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert loaded.document.command_count == count
    assert "失败" in editor.status_label.text()


def test_delete_dimension_and_tolerance_preserves_unselected_geometry(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, -10),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (line,)
    assert not services.kernel.sketches[0].constraints
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].constraints == (dimension,)


def test_mixed_delete_rejects_stale_annotation_selection(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    count = loaded.document.command_count
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids.clear()
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    assert services.kernel.sketches[0].entities == (line,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert loaded.document.command_count == count
    assert "已变化" in editor.status_label.text()


def test_delete_draft_geometry_and_tolerance_together_undo_redo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert not editor.canvas.entities
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert tuple(editor.canvas.entities) == (line,)
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert not editor.canvas.entities


def test_draft_and_tolerance_delete_rolls_back_when_draft_apply_fails(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch import LineEntity

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    text = DrawingText(uuid4().hex, "note", (10, 10))
    assert tools.execute(
        "drawing.text.batch", {"add": [text.to_mapping()], "update": [], "remove": []}
    )
    count = loaded.document.command_count
    pending = (line.entity_id, uuid4().hex)
    editor.canvas.pending_cross_tangencies.append(pending)
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.text_tools is not None
    editor.canvas.text_tools.selected_ids = {text.text_id}

    def fail_draft_apply(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(type(editor.canvas), "replace_draft_entities_atomically", fail_draft_apply)
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert tuple(editor.canvas.entities) == (line,)
    assert editor.canvas.pending_cross_tangencies == [pending]
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_texts == (text,)
    assert loaded.document.command_count == count
    assert "回滚" in editor.status_label.text()


def test_delete_draft_saved_geometry_and_tolerance_together(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    saved = LineEntity(uuid4().hex, (0, 0), (10, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,)), session_identity=0
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    draft = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((draft,))
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    editor.canvas.selected_entity_ids = {draft.entity_id, saved.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert not services.kernel.sketches[0].entities and not editor.canvas.entities
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (saved,)
    assert tuple(editor.canvas.entities) == (draft,)
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert not services.kernel.sketches[0].entities and not editor.canvas.entities


@pytest.mark.parametrize("with_image", (False, True))
@pytest.mark.parametrize("with_text", (False, True))
def test_delete_draft_with_pending_tangency_and_tolerance_undo_redo(
    qtbot: QtBot, with_image: bool, with_text: bool
) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (0, 0), (10, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,)), session_identity=0
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    image_id = None
    if with_image:
        image = QImage(8, 4, QImage.Format.Format_ARGB32)
        image.fill(0xFFFF0000)
        QApplication.clipboard().setImage(image)
        assert editor.canvas.begin_clipboard_paste()
        editor.canvas.add_coordinate_point((30, 30), exact_point=True)
        image_id = services.kernel.drawing_rasters[0].image_id
    first = CircleEntity(uuid4().hex, (5, 5), 5)
    second = LineEntity(uuid4().hex, (10, 0), (20, 5))
    assert editor.canvas.replace_draft_entities((first, second))
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    text = DrawingText(uuid4().hex, "note", (10, 10))
    if with_text:
        assert tools.execute(
            "drawing.text.batch", {"add": [text.to_mapping()], "update": [], "remove": []}
        )
    pair = (saved.entity_id, first.entity_id)
    editor.canvas.pending_cross_tangencies.append(pair)
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    editor.canvas.selected_entity_ids = {first.entity_id}
    if image_id is not None:
        editor.canvas.selected_raster_ids = {image_id}
    if with_text:
        assert editor.canvas.text_tools is not None
        editor.canvas.text_tools.selected_ids = {text.text_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(
        lambda: not unit.is_busy and not services.kernel.drawing_tolerance_frames,
        timeout=10000,
    )
    assert tuple(editor.canvas.entities) == (second,)
    assert not editor.canvas.pending_cross_tangencies
    assert not services.kernel.drawing_rasters
    assert not services.kernel.drawing_texts
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.drawing_tolerance_frames == (frame,),
        timeout=10000,
    )
    assert tuple(editor.canvas.entities) == (first, second)
    assert editor.canvas.pending_cross_tangencies == [pair]
    assert len(services.kernel.drawing_rasters) == int(with_image)
    assert services.kernel.drawing_texts == ((text,) if with_text else ())
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and not services.kernel.drawing_tolerance_frames,
        timeout=10000,
    )
    assert tuple(editor.canvas.entities) == (second,)
    assert not editor.canvas.pending_cross_tangencies
    assert not services.kernel.drawing_rasters
    assert not services.kernel.drawing_texts


def test_delete_unrelated_draft_keeps_pending_tangency(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (0, 0), (10, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,)), session_identity=0
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    circle = CircleEntity(uuid4().hex, (5, 5), 5)
    unrelated = LineEntity(uuid4().hex, (0, 15), (10, 15))
    assert editor.canvas.replace_draft_entities((circle, unrelated))
    pair = (saved.entity_id, circle.entity_id)
    editor.canvas.pending_cross_tangencies.append(pair)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    editor.canvas.selected_entity_ids = {unrelated.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(
        lambda: not unit.is_busy and not services.kernel.drawing_tolerance_frames, timeout=10000
    )
    assert tuple(editor.canvas.entities) == (circle,)
    assert editor.canvas.pending_cross_tangencies == [pair]
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.drawing_tolerance_frames == (frame,),
        timeout=10000,
    )
    assert tuple(editor.canvas.entities) == (circle, unrelated)
    assert editor.canvas.pending_cross_tangencies == [pair]


def test_mixed_delete_rolls_back_if_pending_tangency_changes_during_commit(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    count = loaded.document.command_count
    pending = (uuid4().hex, line.entity_id)
    original = loaded.bus.create_save_checkpoint

    def checkpoint() -> object:
        token = original()
        editor.canvas.pending_cross_tangencies.append(pending)
        return token

    monkeypatch.setattr(loaded.bus, "create_save_checkpoint", checkpoint)
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert tuple(editor.canvas.entities) == (line,)
    assert editor.canvas.pending_cross_tangencies == [pending]
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert loaded.document.command_count == count
    assert "回滚" in editor.status_label.text()


def test_mixed_delete_with_pending_tangency_rejects_locked_text(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("TEXT_LOCK"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None and editor.canvas.text_tools is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    text = DrawingText(uuid4().hex, "note", (10, 10), layer_name="TEXT_LOCK")
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute(
        "drawing.text.batch", {"add": [text.to_mapping()], "update": [], "remove": []}
    )
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "TEXT_LOCK" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    sync(window)
    pair = (uuid4().hex, line.entity_id)
    editor.canvas.pending_cross_tangencies.append(pair)
    count = loaded.document.command_count
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.text_tools.selected_ids = {text.text_id}
    assert editor.canvas.delete_selected()
    assert tuple(editor.canvas.entities) == (line,)
    assert editor.canvas.pending_cross_tangencies == [pair]
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_texts == (text,)
    assert loaded.document.command_count == count
    assert "锁定" in editor.status_label.text()


@pytest.mark.parametrize("case", ("member", "source", "apply_failure", "pending_changed"))
def test_delete_pending_array_member_text_and_tolerance_undo_redo(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path, case: str
) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch import LineEntity

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.pending_associative_arrays) == 1
    array = editor.canvas.pending_associative_arrays[0]
    member_id = array.members[0].target.entity_id
    before = tuple(editor.canvas.entities)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None and editor.canvas.text_tools is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    text = DrawingText(uuid4().hex, "note", (10, 10))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute(
        "drawing.text.batch", {"add": [text.to_mapping()], "update": [], "remove": []}
    )
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    editor.canvas.selected_entity_ids = {source.entity_id if case == "source" else member_id}
    editor.canvas.text_tools.selected_ids = {text.text_id}
    if case == "apply_failure":

        def fail_draft_apply(*_args: object, **_kwargs: object) -> bool:
            return False

        monkeypatch.setattr(
            type(editor.canvas), "replace_draft_entities_atomically", fail_draft_apply
        )
    if case == "pending_changed":
        original_checkpoint = loaded.bus.create_save_checkpoint

        def checkpoint() -> object:
            token = original_checkpoint()
            editor.canvas.pending_associative_arrays.append(array)
            return token

        monkeypatch.setattr(loaded.bus, "create_save_checkpoint", checkpoint)
    assert editor.canvas.delete_selected()
    if case != "member":
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert tuple(editor.canvas.entities) == before
        assert editor.canvas.pending_associative_arrays == (
            [array, array] if case == "pending_changed" else [array]
        )
        assert services.kernel.drawing_tolerance_frames == (frame,)
        assert services.kernel.drawing_texts == (text,)
        assert ("阵列" if case == "source" else "回滚") in editor.status_label.text()
        return
    qtbot.waitUntil(
        lambda: not unit.is_busy and not services.kernel.drawing_tolerance_frames, timeout=10000
    )
    assert all(entity.entity_id != member_id for entity in editor.canvas.entities)
    assert editor.canvas.pending_associative_arrays[0].members[0].erased_index is not None
    assert not services.kernel.drawing_texts
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.drawing_tolerance_frames == (frame,),
        timeout=10000,
    )
    assert tuple(editor.canvas.entities) == before
    assert editor.canvas.pending_associative_arrays == [array]
    assert services.kernel.drawing_texts == (text,)
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and not services.kernel.drawing_tolerance_frames, timeout=10000
    )
    assert all(entity.entity_id != member_id for entity in editor.canvas.entities)
    assert editor.canvas.pending_associative_arrays[0].members[0].erased_index is not None
    assert not services.kernel.drawing_texts
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert services.kernel.associative_arrays[0].members[0].erased_index is not None
    from mycad.core.persistence import save_document

    loaded = window.loaded_document()
    assert loaded is not None
    saved = tmp_path / "pending-array-erasure.my2d"
    save_document(loaded.document, saved)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, saved)
    assert reopened.kernel.associative_arrays[0].members[0].erased_index is not None


@pytest.mark.parametrize(
    "case",
    (
        "success",
        "apply_failure",
        "revision_changed",
        "selected_dimension",
        "draft_member_dimension",
        "unselected_draft_member_dimension",
        "saved_dimension",
        "saved_member_dimension",
        "attached_dimension",
        "attached_member",
        "unselected_datum",
        "unselected_frame",
        "unselected_dimension_frame",
        "unselected_dimension_datum",
        "referenced_datum",
    ),
)
def test_delete_pending_and_saved_array_members_with_annotations_undo_redo(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch, case: str
) -> None:
    from uuid import uuid4

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    member = LineEntity(uuid4().hex, (5, 0), (7, 0))
    saved_dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (
            SketchGeometryReference(
                member.entity_id if case == "saved_member_dimension" else source.entity_id,
                "geometry",
            ),
        ),
        value=2,
        unit="mm",
        position_mm=(0, 5),
    )
    sketch = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (source, member),
        (saved_dimension,)
        if case
        in (
            "saved_dimension",
            "saved_member_dimension",
            "attached_dimension",
            "unselected_dimension_frame",
            "unselected_dimension_datum",
        )
        else (),
    )
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    member_ref = ArrayEntityRef(sketch.sketch_id, member.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, member_ref, 0, 1),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    draft_source = LineEntity(uuid4().hex, (0, 20), (2, 20))
    assert editor.canvas.replace_draft_entities((draft_source,))
    editor.canvas.selected_entity_ids = {draft_source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    pending = editor.canvas.pending_associative_arrays[0]
    pending_member = pending.members[0].target.entity_id
    before_draft = tuple(editor.canvas.entities)
    tools, text_tools = editor.canvas.geometric_tolerance_tools, editor.canvas.text_tools
    assert tools is not None and tools.execute is not None and text_tools is not None
    protected_datum = None
    protected_frame = None
    if case == "attached_dimension":
        from mycad.core.geometric_tolerance import AnnotationAttachment

        frame = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 5),
            leader_target_mm=(0, 5),
            leader_anchor_offset=(0, -2),
            leader_annotation_attachment=AnnotationAttachment(
                "sketch_dimension", saved_dimension.constraint_id, (0, 0), sketch.sketch_id
            ),
        )
    elif case == "attached_member":
        from mycad.core.geometric_tolerance import DatumAttachment

        frame = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 5),
            leader_target_mm=(5, 0),
            leader_anchor_offset=(0, -2),
            leader_attachment=DatumAttachment(
                sketch.sketch_id, SketchGeometryReference(member.entity_id, "start")
            ),
        )
    elif case == "referenced_datum":
        from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference

        protected_datum = DatumIdentifier(uuid4().hex, "A", (8, 3), (5, 0))
        frame = FeatureControlFrame(
            uuid4().hex,
            (
                ToleranceRow(
                    "position",
                    0.1,
                    2,
                    datums=(DatumReference("A", datum_id=protected_datum.datum_id),),
                ),
            ),
            (10, 5),
        )
        assert tools.execute(
            "drawing.tolerance.batch", {"add_datums": [protected_datum.to_mapping()]}
        )
    else:
        frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    text = DrawingText(uuid4().hex, "note", (10, 10))
    if case == "unselected_datum":
        from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier

        protected_datum = DatumIdentifier(
            uuid4().hex,
            "A",
            (8, 3),
            (5, 0),
            attachment=DatumAttachment(
                sketch.sketch_id, SketchGeometryReference(member.entity_id, "start")
            ),
        )
        assert tools.execute(
            "drawing.tolerance.batch", {"add_datums": [protected_datum.to_mapping()]}
        )
    if case in ("unselected_frame", "unselected_dimension_frame"):
        from mycad.core.geometric_tolerance import AnnotationAttachment, DatumAttachment

        protected_frame = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (20, 5),
            leader_target_mm=(5, 0) if case == "unselected_frame" else (0, 5),
            leader_anchor_offset=(0, -2),
            leader_attachment=(
                DatumAttachment(
                    sketch.sketch_id, SketchGeometryReference(member.entity_id, "start")
                )
                if case == "unselected_frame"
                else None
            ),
            leader_annotation_attachment=(
                AnnotationAttachment(
                    "sketch_dimension", saved_dimension.constraint_id, (0, 0), sketch.sketch_id
                )
                if case == "unselected_dimension_frame"
                else None
            ),
        )
        assert tools.execute(
            "drawing.tolerance.batch", {"add_frames": [protected_frame.to_mapping()]}
        )
    if case == "unselected_dimension_datum":
        from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

        protected_datum = DatumIdentifier(
            uuid4().hex,
            "A",
            (8, 3),
            (0, 5),
            annotation_attachment=AnnotationAttachment(
                "sketch_dimension", saved_dimension.constraint_id, (0, 0), sketch.sketch_id
            ),
        )
        assert tools.execute(
            "drawing.tolerance.batch", {"add_datums": [protected_datum.to_mapping()]}
        )
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute(
        "drawing.text.batch", {"add": [text.to_mapping()], "update": [], "remove": []}
    )
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        protected_datum.datum_id
        if case == "referenced_datum" and protected_datum
        else frame.frame_id,
        "datum" if case == "referenced_datum" else "frame",
        {protected_datum.datum_id}
        if case == "referenced_datum" and protected_datum
        else {frame.frame_id},
    )
    text_tools.selected_ids = {text.text_id}
    editor.canvas.selected_entity_ids = {member.entity_id, pending_member}
    dimension: SketchConstraint | None = None
    if case in (
        "selected_dimension",
        "draft_member_dimension",
        "unselected_draft_member_dimension",
    ):
        dimension = SketchConstraint(
            uuid4().hex,
            "length",
            (
                SketchGeometryReference(
                    pending_member if case != "selected_dimension" else draft_source.entity_id,
                    "geometry",
                ),
            ),
            value=2,
            unit="mm",
            position_mm=(0, 25),
        )
        editor.canvas.constraints.append(dimension)
        if case != "unselected_draft_member_dimension":
            editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    elif case in (
        "saved_dimension",
        "saved_member_dimension",
        "attached_dimension",
        "unselected_dimension_frame",
        "unselected_dimension_datum",
    ):
        editor.canvas.selected_constraint_ids = {saved_dimension.constraint_id}
    count = loaded.document.command_count
    if case == "apply_failure":

        def fail_draft_apply(*_args: object, **_kwargs: object) -> bool:
            return False

        monkeypatch.setattr(
            type(editor.canvas), "replace_draft_entities_atomically", fail_draft_apply
        )
    external_text = DrawingText(uuid4().hex, "external", (12, 12))
    if case == "revision_changed":
        original_checkpoint = loaded.bus.create_save_checkpoint

        def checkpoint() -> object:
            token = original_checkpoint()
            loaded.bus.execute("drawing.text.add", external_text.to_mapping(), "local")
            return token

        monkeypatch.setattr(loaded.bus, "create_save_checkpoint", checkpoint)
    assert editor.canvas.delete_selected()
    if case in ("unselected_dimension_frame", "unselected_dimension_datum"):
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert "尺寸仍被标注附着" in editor.status_label.text()
        assert "请先解除附着" in editor.status_label.text()
        assert "ReplayFailure" not in editor.status_label.text()
        assert services.kernel.drawing_tolerance_frames == (
            (protected_frame, frame) if protected_frame else (frame,)
        )
        if protected_datum is not None:
            assert services.kernel.drawing_datum_identifiers == (protected_datum,)
        assert services.kernel.associative_arrays == (array,)
        assert editor.canvas.pending_associative_arrays == [pending]
        assert tuple(editor.canvas.entities) == before_draft
        assert services.kernel.sketches[0].constraints == sketch.constraints
        assert services.kernel.drawing_texts == (text,)
        assert loaded.document.command_count == count
        return
    if case not in (
        "success",
        "selected_dimension",
        "draft_member_dimension",
        "saved_dimension",
        "saved_member_dimension",
        "attached_dimension",
        "attached_member",
        "unselected_datum",
        "unselected_frame",
        "unselected_dimension_frame",
    ):
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert services.kernel.associative_arrays == (array,)
        assert editor.canvas.pending_associative_arrays == [pending]
        assert tuple(editor.canvas.entities) == before_draft
        if case == "unselected_draft_member_dimension":
            assert dimension is not None
            assert editor.canvas.constraints == [dimension]
        assert services.kernel.drawing_tolerance_frames == (frame,)
        if protected_datum is not None:
            assert services.kernel.drawing_datum_identifiers == (protected_datum,)
        assert services.kernel.drawing_texts == (
            (text, external_text) if case == "revision_changed" else (text,)
        )
        assert loaded.document.command_count == count + int(case == "revision_changed")
        expected = (
            "约束"
            if case == "unselected_draft_member_dimension"
            else "基准仍被公差框引用"
            if case == "referenced_datum"
            else "失败"
            if case == "revision_changed"
            else "回滚"
        )
        assert expected in editor.status_label.text()
        return
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and (
                services.kernel.drawing_tolerance_frames
                == ((protected_frame,) if protected_frame else ())
                or "失败" in editor.status_label.text()
            )
        ),
        timeout=10000,
    )
    assert services.kernel.drawing_tolerance_frames == (
        (protected_frame,) if protected_frame else ()
    ), editor.status_label.text()
    if protected_frame is not None:
        assert cast("Callable[..., bool]", _private_member(tools, "_frame_attachment_lost"))(
            protected_frame
        )
    assert services.kernel.associative_arrays[0].members[0].erased_index is not None
    assert editor.canvas.pending_associative_arrays[0].members[0].erased_index is not None
    assert not services.kernel.drawing_texts
    assert not editor.canvas.selected_entity_ids
    assert not text_tools.selected_ids
    assert not tools.selected_ids
    assert not editor.canvas.constraints
    assert not services.kernel.sketches[0].constraints
    if protected_datum is not None:
        assert services.kernel.drawing_datum_identifiers == (protected_datum,)
        assert not services.kernel.datum_attachment_resolved(protected_datum.datum_id)
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and services.kernel.drawing_tolerance_frames
            == ((protected_frame, frame) if protected_frame else (frame,))
        ),
        timeout=10000,
    )
    assert services.kernel.associative_arrays[0] == array
    assert services.kernel.sketches[0].constraints == sketch.constraints
    assert editor.canvas.pending_associative_arrays == [pending]
    assert tuple(editor.canvas.entities) == before_draft
    assert services.kernel.drawing_texts == (text,)
    assert len(editor.canvas.constraints) == int(
        case in ("selected_dimension", "draft_member_dimension")
    )
    if protected_datum is not None:
        assert services.kernel.datum_attachment_resolved(protected_datum.datum_id)
    if protected_frame is not None:
        assert not cast("Callable[..., bool]", _private_member(tools, "_frame_attachment_lost"))(
            protected_frame
        )
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and services.kernel.drawing_tolerance_frames
            == ((protected_frame,) if protected_frame else ())
        ),
        timeout=10000,
    )
    assert services.kernel.associative_arrays[0].members[0].erased_index is not None
    assert editor.canvas.pending_associative_arrays[0].members[0].erased_index is not None
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    from mycad.core.persistence import save_document

    saved = tmp_path / "mixed-arrays.my2d"
    save_document(loaded.document, saved)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, saved)
    assert len(reopened.kernel.associative_arrays) == 2
    assert all(
        item.members[0].erased_index is not None for item in reopened.kernel.associative_arrays
    )
    if protected_datum is not None:
        assert not reopened.kernel.datum_attachment_resolved(protected_datum.datum_id)
    if protected_frame is not None:
        from mycad.core.geometric_tolerance_attachment import resolve_attachment_local

        assert reopened.kernel.drawing_tolerance_frames == (protected_frame,)
        if case == "unselected_frame":
            assert protected_frame.leader_attachment is not None
            assert (
                resolve_attachment_local(
                    protected_frame.leader_attachment,
                    {entity.entity_id: entity for entity in reopened.kernel.sketches[0].entities},
                )
                is None
            )
        else:
            assert protected_frame.leader_annotation_attachment is not None
            assert not reopened.kernel.sketches[0].constraints


def test_delete_array_member_and_tolerance_together_undo_redo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    member = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, member))
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    member_ref = ArrayEntityRef(sketch.sketch_id, member.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, member_ref, 0, 1),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    editor.canvas.selected_entity_ids = {member.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (source,)
    assert services.kernel.associative_arrays[0].members[0].erased_index is not None
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (source, member)
    assert services.kernel.associative_arrays[0].members[0].erased_index is None
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (source,)


def test_array_and_datum_delete_rolls_back_when_frame_still_references_datum(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.drawing_text import DrawingText
    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    member = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, member))
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    member_ref = ArrayEntityRef(sketch.sketch_id, member.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, member_ref, 0, 1),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (4, 5),
    )
    assert tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    text = DrawingText(uuid4().hex, "note", (0, 0))
    assert tools.execute(
        "drawing.text.batch", {"add": [text.to_mapping()], "update": [], "remove": []}
    )
    text_tools = editor.canvas.text_tools
    assert text_tools is not None
    text_tools.selected_ids = {text.text_id}
    count = loaded.document.command_count
    tools.selected_id, tools.selected_kind = datum.datum_id, "datum"
    tools.selected_ids = {datum.datum_id}
    editor.canvas.selected_entity_ids = {member.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities == (source, member)
    assert services.kernel.associative_arrays[0].members[0].erased_index is None
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_texts == (text,)
    assert loaded.document.command_count == count
    assert "失败" in editor.status_label.text()


@pytest.mark.parametrize("with_dimension", [False, True])
def test_delete_array_tolerance_text_and_image_together(qtbot: QtBot, with_dimension: bool) -> None:
    import base64
    import struct
    import zlib
    from uuid import uuid4

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    member = LineEntity(uuid4().hex, (5, 0), (7, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(member.entity_id, "geometry"),),
        2,
        "mm",
        driving=False,
        position_mm=(6, -2),
    )
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (source, member), (dimension,) if with_dimension else ()
    )
    source_ref, member_ref = (
        ArrayEntityRef(sketch.sketch_id, source.entity_id),
        ArrayEntityRef(sketch.sketch_id, member.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, member_ref, 0, 1),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools, text_tools = editor.canvas.geometric_tolerance_tools, editor.canvas.text_tools
    assert tools is not None and tools.execute is not None and text_tools is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    text = DrawingText(uuid4().hex, "note", (0, 0))
    image = DrawingRaster(uuid4().hex, base64.b64encode(png).decode("ascii"), (0, 0), 1, 1)
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute(
        "drawing.text.batch", {"add": [text.to_mapping()], "update": [], "remove": []}
    )
    assert tools.execute("drawing.raster.add", image.to_mapping(version=2))
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    editor.canvas.selected_entity_ids = {member.entity_id}
    editor.canvas.selected_constraint_ids = {dimension.constraint_id} if with_dimension else set()
    editor.canvas.selected_raster_ids = {image.image_id}
    text_tools.selected_ids = {text.text_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (source,)
    assert not services.kernel.sketches[0].constraints
    assert not services.kernel.drawing_texts and not services.kernel.drawing_rasters
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (source, member)
    assert services.kernel.sketches[0].constraints == ((dimension,) if with_dimension else ())
    assert services.kernel.drawing_texts == (text,) and services.kernel.drawing_rasters == (image,)
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (source,)
    assert not services.kernel.drawing_texts and not services.kernel.drawing_rasters


@pytest.mark.parametrize("dimension_target", ["source", "member"])
@pytest.mark.parametrize("include_draft", [False, True])
@pytest.mark.parametrize("fail_draft_apply", [False, True])
def test_delete_array_member_dimension_and_tolerance_together(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    dimension_target: str,
    include_draft: bool,
    fail_draft_apply: bool,
) -> None:
    if fail_draft_apply and not include_draft:
        pytest.skip("draft application is not used without a draft")
    from uuid import uuid4

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    member = LineEntity(uuid4().hex, (5, 0), (7, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (
            SketchGeometryReference(
                source.entity_id if dimension_target == "source" else member.entity_id, "geometry"
            ),
        ),
        2,
        "mm",
        driving=False,
        position_mm=(1, -2),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, member), (dimension,))
    source_ref, member_ref = (
        ArrayEntityRef(sketch.sketch_id, source.entity_id),
        ArrayEntityRef(sketch.sketch_id, member.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, member_ref, 0, 1),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    draft = LineEntity(uuid4().hex, (0, 10), (2, 10))
    if include_draft:
        assert editor.canvas.replace_draft_entities((draft,))
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    tools.selected_ids = {frame.frame_id}
    editor.canvas.selected_entity_ids = {
        member.entity_id,
        *([draft.entity_id] if include_draft else []),
    }
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    count = loaded.document.command_count
    if fail_draft_apply:
        monkeypatch.setattr(
            type(editor.canvas), "replace_draft_entities_atomically", _fail_draft_apply
        )
    assert editor.canvas.delete_selected()
    if fail_draft_apply:
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert services.kernel.sketches[0].entities == (source, member)
        assert services.kernel.sketches[0].constraints == (dimension,)
        assert services.kernel.associative_arrays[0].members[0].erased_index is None
        assert services.kernel.drawing_tolerance_frames == (frame,)
        assert tuple(editor.canvas.entities) == (draft,)
        assert loaded.document.command_count == count
        assert "回滚" in editor.status_label.text()
        return
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (source,)
    assert not services.kernel.sketches[0].constraints
    assert not editor.canvas.entities
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (source, member)
    assert services.kernel.sketches[0].constraints == (dimension,)
    assert tuple(editor.canvas.entities) == ((draft,) if include_draft else ())
    assert services.kernel.associative_arrays[0].members[0].erased_index is None
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    assert services.kernel.sketches[0].entities == (source,)
    assert not services.kernel.sketches[0].constraints
    assert not editor.canvas.entities


def test_array_dimension_datum_delete_rolls_back_if_datum_in_use(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.drawing_text import DrawingText
    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source, member = (
        LineEntity(uuid4().hex, (0, 0), (2, 0)),
        LineEntity(uuid4().hex, (5, 0), (7, 0)),
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(member.entity_id, "geometry"),),
        2,
        "mm",
        driving=False,
        position_mm=(6, -2),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, member), (dimension,))
    source_ref, member_ref = (
        ArrayEntityRef(sketch.sketch_id, source.entity_id),
        ArrayEntityRef(sketch.sketch_id, member.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, member_ref, 0, 1),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (4, 5),
    )
    assert tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    text = DrawingText(uuid4().hex, "note", (0, 0))
    assert tools.execute(
        "drawing.text.batch", {"add": [text.to_mapping()], "update": [], "remove": []}
    )
    text_tools = editor.canvas.text_tools
    assert text_tools is not None
    text_tools.selected_ids = {text.text_id}
    count = loaded.document.command_count
    tools.selected_id, tools.selected_kind = datum.datum_id, "datum"
    tools.selected_ids = {datum.datum_id}
    editor.canvas.selected_entity_ids = {member.entity_id}
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities == (source, member)
    assert services.kernel.sketches[0].constraints == (dimension,)
    assert services.kernel.associative_arrays[0].members[0].erased_index is None
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_texts == (text,)
    assert loaded.document.command_count == count
    assert "失败" in editor.status_label.text()


def test_legacy_cross_kind_identity_collision_cannot_be_selected_ambiguously(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    identity = uuid4().hex
    frame = FeatureControlFrame(identity, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    datum = DatumIdentifier(identity, "A", (30, 30), (30, 25))
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
        version=6,
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert tools.selected_id is None and not tools.selected_ids
    assert "身份" in editor.canvas.message and "重复" in editor.canvas.message
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_repair_legacy_annotation_identities_preserves_links_and_undo(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    identity = uuid4().hex
    datum = DatumIdentifier(identity, "A", (0, 0), (0, -5))
    frame = FeatureControlFrame(
        identity,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", identity),)),),
        (10, 5),
    )
    dimension = DetachedDimension(identity, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
        version=6,
    )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local", version=5
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    assert tools.handle_command("REPAIRANNOTATIONIDS")
    repaired_frame = services.kernel.drawing_tolerance_frames[0]
    repaired_datum = services.kernel.drawing_datum_identifiers[0]
    repaired_dimension = services.kernel.drawing_reference_dimensions[0]
    assert (
        len({repaired_frame.frame_id, repaired_datum.datum_id, repaired_dimension.dimension_id})
        == 3
    )
    assert repaired_datum == datum
    assert repaired_frame.rows[0].datums == (DatumReference("A", repaired_datum.datum_id),)
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_reference_dimensions == (dimension,)
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (repaired_frame,)
        ),
        timeout=10000,
    )
    assert services.kernel.drawing_datum_identifiers == (repaired_datum,)
    assert services.kernel.drawing_reference_dimensions == (repaired_dimension,)
    path = tmp_path / "identity-repair.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (repaired_frame,)
    assert reopened.kernel.drawing_datum_identifiers == (repaired_datum,)
    assert reopened.kernel.drawing_reference_dimensions == (repaired_dimension,)


@pytest.mark.parametrize("change", ["revision", "selection"])
def test_reattach_cancels_if_document_or_selection_changes(qtbot: QtBot, change: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    first = DatumIdentifier(uuid4().hex, "A", (0, 5), (0, 0))
    second = DatumIdentifier(uuid4().hex, "B", (10, 5), (10, 0))
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [first.to_mapping(), second.to_mapping()]},
        "local",
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and _select_annotation(tools, first.datum_id, "datum")
    assert tools.handle_command("REATTACH") and tools.pending_reattach
    if change == "revision":
        layers = services.kernel.drawing_layers.add(SketchLayer("new"))
        loaded.bus.execute(
            "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
        sync(window)
    else:
        assert _select_annotation(tools, second.datum_id, "datum")
    count = loaded.document.command_count
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    assert not tools.pending_reattach
    assert "变化" in editor.canvas.message
    assert loaded.document.command_count == count
    assert services.kernel.drawing_datum_identifiers == (first, second)


def test_reattach_requires_one_datum_and_has_toolbar_entry(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, 5))
    second = DatumIdentifier(uuid4().hex, "B", (10, 0), (10, 5))
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [first.to_mapping(), second.to_mapping()]},
        "local",
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    assert tools.handle_command("REATTACH")
    assert not tools.pending_reattach and "选择" in editor.canvas.message
    assert _select_annotation(tools, first.datum_id, "datum")
    assert _select_annotation(tools, second.datum_id, "datum", additive=True)
    assert tools.handle_command("REATTACH")
    assert not tools.pending_reattach and "一个" in editor.canvas.message
    assert services.kernel.drawing_datum_identifiers == (first, second)
    assert _select_annotation(tools, first.datum_id, "datum")
    editor.canvas.selected_entity_ids = {uuid4().hex}
    assert tools.handle_command("REATTACH")
    assert not tools.pending_reattach and "一个" in editor.canvas.message
    assert tools.handle_command("DETACHDATUM")
    assert "一个" in editor.canvas.message
    editor.canvas.selected_entity_ids.clear()
    menu = next(
        action.menu()
        for action in editor.dimension_toolbar.actions()
        if action.text() == "基准操作"
    )
    assert isinstance(menu, QMenu)
    action = next(action for action in menu.actions() if action.text() == "重新关联基准")
    action.trigger()
    assert tools.pending_reattach
    assert tools.cancel()
    assert tools.handle_command("REATTACH")
    assert tools.pending_reattach


def test_detach_frame_preserves_target_and_supports_undo(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, FeatureControlFrame, ToleranceRow
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        layer_name="GDT",
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and _select_annotation(tools, frame.frame_id, "frame")
    menu = next(
        action.menu()
        for action in editor.dimension_toolbar.actions()
        if action.text() == "基准操作"
    )
    assert isinstance(menu, QMenu)
    assert any(action.text() == "解除公差框附着" for action in menu.actions())
    editor.drawing_command_bar.input.setText("DETACHFRAME")
    editor.drawing_command_bar.submit()
    detached = services.kernel.drawing_tolerance_frames[0]
    assert detached.leader_attachment is None
    assert detached.leader_target_mm == frame.leader_target_mm
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "GDT" else layer for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    sync(window)
    assert _select_annotation(tools, frame.frame_id, "frame")
    count = loaded.document.command_count
    assert tools.handle_command("DETACHFRAME")
    assert loaded.document.command_count == count
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_frame_detach_edit_and_reattach(qtbot: QtBot, tmp_path: Path) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, FeatureControlFrame, ToleranceRow
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (poly,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (25, 20),
        leader_target_mm=(5, 0),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(poly.entity_id, "segment", 0), 0.5, 2
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and _select_annotation(tools, frame.frame_id, "frame")
    assert tools.handle_command("DETACHFRAME")
    changed = replace(sketch, entities=(replace(poly, points_mm=((0, 0), (10, 10), (10, 0))),))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    sync(window)
    detached = services.kernel.drawing_tolerance_frames[0]
    assert detached.leader_attachment is None
    editor.canvas.set_tool("选择元素")
    assert _select_annotation(tools, frame.frame_id, "frame")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    assert tools.handle_command("5,5")
    reattached = services.kernel.drawing_tolerance_frames[0]
    assert reattached.leader_target_mm == pytest.approx((5, 5))
    assert reattached.leader_attachment is not None
    assert reattached.leader_attachment.reference == SketchGeometryReference(
        poly.entity_id, "segment", 0
    )
    path = tmp_path / "frame-reattached.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (reattached,)


def test_detach_datum_preserves_position_and_supports_undo_redo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and _select_annotation(tools, datum.datum_id, "datum")
    editor.drawing_command_bar.input.setText("DETACHDATUM")
    editor.drawing_command_bar.submit()
    detached = services.kernel.drawing_datum_identifiers[0]
    assert detached.attachment is None
    assert detached.position_mm == datum.position_mm and detached.target_mm == datum.target_mm
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_datum_identifiers == (datum,)
        ),
        timeout=10000,
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_datum_identifiers == (detached,)
        ),
        timeout=10000,
    )
    count = loaded.document.command_count
    assert tools.handle_command("DETACHDATUM")
    assert loaded.document.command_count == count
    menu = next(
        action.menu()
        for action in editor.dimension_toolbar.actions()
        if action.text() == "基准操作"
    )
    assert isinstance(menu, QMenu)
    assert any(action.text() == "解除基准附着" for action in menu.actions())


def test_detach_edit_and_reattach_curve_datum(qtbot: QtBot, tmp_path: Path) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.exceptions import ValidationError
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, DatumReference
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    curve = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 5),
        (10, 0),
        attachment=DatumAttachment(
            sketch.sketch_id,
            SketchGeometryReference(curve.entity_id, "segment", 0),
            0.5,
            segment_count=2,
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (30, 30),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    changed = replace(curve, points_mm=tuple(reversed(curve.points_mm)))
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    revision = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ]
    }
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute("drawing.sketch.revise", revision, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and _select_annotation(tools, datum.datum_id, "datum")
    assert tools.handle_command("DETACHDATUM")
    loaded.bus.execute("drawing.sketch.revise", revision, "local")
    sync(window)
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (10, 0)
    assert tools.handle_command("REATTACH")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((20, 10))
    )
    reattached = services.kernel.drawing_datum_identifiers[0]
    assert reattached.attachment is not None
    assert reattached.attachment.reference == SketchGeometryReference(curve.entity_id, "segment", 0)
    assert reattached.target_mm == (20, 10)
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_datum_identifiers[0].attachment is None
        ),
        timeout=10000,
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_datum_identifiers == (reattached,)
        ),
        timeout=10000,
    )
    path = tmp_path / "reattached.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (reattached,)
    assert reopened.kernel.drawing_tolerance_frames == (frame,)
    assert reopened.kernel.datum_attachment_resolved(datum.datum_id)


def test_detach_datum_rejects_locked_layer(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (0, 0),
        layer_name="GDT",
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "GDT" else layer for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and _select_annotation(tools, datum.datum_id, "datum")
    count = loaded.document.command_count
    assert tools.handle_command("DETACHDATUM")
    assert loaded.document.command_count == count
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert editor.canvas.message


def test_repair_annotation_identities_without_conflicts_is_noop(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    count = loaded.document.command_count
    assert tools.handle_command("REPAIRANNOTATIONIDS")
    assert loaded.document.command_count == count
    assert "没有需要修复" in editor.canvas.message
    menu = next(
        action.menu()
        for action in editor.dimension_toolbar.actions()
        if action.text() == "基准操作"
    )
    assert isinstance(menu, QMenu)
    assert any(action.text() == "修复标注身份" for action in menu.actions())


def test_repair_legacy_annotation_identities_rolls_back_locked_frame(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    identity = uuid4().hex
    datum = DatumIdentifier(identity, "A", (0, 0), (0, -5))
    frame = FeatureControlFrame(
        identity, (ToleranceRow("flatness", 0.1, 2),), (10, 5), layer_name="GDT"
    )
    dimension = DetachedDimension(identity, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
        version=6,
    )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local", version=5
    )
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "GDT" else layer for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    count = loaded.document.command_count
    assert tools.handle_command("REPAIRANNOTATIONIDS")
    assert loaded.document.command_count == count
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_reference_dimensions == (dimension,)
    assert editor.canvas.message


def test_frame_layout_cache_tracks_text_style_updates(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    text_tools = editor.canvas.text_tools
    assert tools is not None and text_tools is not None
    font = TextStyle(style_id="frame-font", name="公差字体", height_mm=3.5)
    text_tools.sync((), TextStyleTable((TextStyle(), font)))
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0), text_style_id=font.style_id
    )
    original = tools.screen_bounds(frame)
    text_tools.sync((), TextStyleTable((TextStyle(), replace(font, height_mm=7))))
    resized = tools.screen_bounds(frame)
    assert resized.width() == pytest.approx(original.width() * 2)
    assert resized.height() == pytest.approx(original.height() * 2)


def test_create_and_edit_frame_text_style(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools, text_tools = editor.canvas.geometric_tolerance_tools, editor.canvas.text_tools
    assert tools is not None and text_tools is not None
    styles = TextStyleTable((TextStyle(), TextStyle(style_id="iso", name="ISO", height_mm=7)))
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local")
    text_tools.sync((), styles)

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.text_style.setCurrentIndex(dialog.text_style.findData("iso"))
        dialog.accept()

    QTimer.singleShot(20, create)
    tools.begin_frame()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.text_style_id == "iso"

    def edit() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        assert dialog.text_style.currentData() == "iso"
        dialog.text_style.setCurrentIndex(dialog.text_style.findData(None))
        dialog.accept()

    QTimer.singleShot(20, edit)
    QTest.mouseDClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert services.kernel.drawing_tolerance_frames[0].text_style_id is None
    window.request_undo()
    qtbot.waitUntil(
        lambda: services.kernel.drawing_tolerance_frames[0].text_style_id == "iso", timeout=10000
    )
    assert services.kernel.drawing_tolerance_frames[0].text_style_id == "iso"


def test_select_frame_reports_unavailable_font(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(tools.manager, "missing_glyphs", _missing_glyph)
    missing = TextStyle("missing", "图纸字体", font_family="MyCAD-Definitely-Not-Installed")
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), missing)).to_mapping(), "local"
    )
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (20, 10), text_style_id="missing"
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert "不可用" in editor.status_label.text()
    assert "MyCAD-Definitely-Not-Installed" in editor.status_label.text()
    assert "缺少字符：字" in editor.status_label.text()


def test_datum_bounds_follow_text_style(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools, text_tools = editor.canvas.geometric_tolerance_tools, editor.canvas.text_tools
    assert tools is not None and text_tools is not None
    style = TextStyle("large", "基准字体", height_mm=7, width_factor=2)
    text_tools.sync((), TextStyleTable((TextStyle(), style)))
    datum = DatumIdentifier(uuid4().hex, "ABC", (0, 0), (0, -5))
    normal = tools.datum_screen_bounds(datum)
    large = tools.datum_screen_bounds(
        DatumIdentifier(
            datum.datum_id, datum.label, datum.position_mm, datum.target_mm, text_style_id="large"
        )
    )
    assert large.width() > normal.width()
    assert large.height() > normal.height()


def test_select_datum_reports_font_substitution_and_missing_glyph(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(tools.manager, "missing_glyphs", _missing_glyph)
    missing = TextStyle("missing", "基准字体", font_family="MyCAD-Definitely-Not-Installed")
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), missing)).to_mapping(), "local"
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (20, 0), text_style_id="missing")
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=tools.datum_screen_bounds(datum).center().toPoint(),
    )
    assert "MyCAD-Definitely-Not-Installed" in editor.status_label.text()
    assert "缺少字符：字" in editor.status_label.text()


def test_edit_datum_text_style_from_menu_and_undo(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    style = TextStyle("datum-font", "基准字体", height_mm=7)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (20, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=tools.datum_screen_bounds(datum).center().toPoint(),
    )
    monkeypatch.setattr(QInputDialog, "getItem", _text_response("基准字体 (datum-font)"))
    window.act_datum_text_style.trigger()
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.text_style_id == "datum-font"
    assert tools.datum_screen_bounds(updated).height() > tools.datum_screen_bounds(datum).height()
    window.request_undo()
    qtbot.waitUntil(
        lambda: services.kernel.drawing_datum_identifiers[0].text_style_id is None, timeout=10000
    )
    bar = editor.drawing_command_bar.input
    bar.setText("DATUMSTYLE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert services.kernel.drawing_datum_identifiers[0].text_style_id == "datum-font"


def test_selected_frame_move_and_copy_via_command_bar(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    tools.begin_frame()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    original = services.kernel.drawing_tolerance_frames[0]
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=tools.screen_bounds(original).center().toPoint(),
    )
    bar = editor.drawing_command_bar.input
    for command in ("MOVE", "0,0", "5,3"):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    moved = services.kernel.drawing_tolerance_frames[0]
    assert moved.position_mm == (original.position_mm[0] + 5, original.position_mm[1] + 3)
    for command in ("COPY", "0,0", "10,0"):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    frames = services.kernel.drawing_tolerance_frames
    assert len(frames) == 2
    assert frames[0] == moved
    assert frames[1].position_mm == (moved.position_mm[0] + 10, moved.position_mm[1])
    assert frames[1].frame_id != moved.frame_id


def test_datum_placement_and_frame_reference_are_linked(qtbot: QtBot, monkeypatch: object) -> None:
    from pytest import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None

    def get_text(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", get_text)
    tools.begin_datum()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, -10))
    )
    datum = services.kernel.drawing_datum_identifiers[0]

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.rows[0].characteristic.setCurrentIndex(
            dialog.rows[0].characteristic.findData("position")
        )
        dialog.rows[0].datums[0].setText("A")
        dialog.accept()

    QTimer.singleShot(20, accept)
    tools.begin_frame()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    assert services.kernel.drawing_tolerance_frames[0].rows[0].datums[0].datum_id == datum.datum_id


def test_pending_tolerance_blocks_document_switch_and_new(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    session = DocumentSession()
    window = MainWindow(services=services, document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    first = session.active
    window.act_new_drawing.trigger()
    second = session.active
    assert first is not None and second is not None
    window.activate_session_document(first.loaded.document.document_id)
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    tools.begin_frame()
    assert tools.pending
    assert not editor.canvas.set_tool("直线")
    window.request_undo()
    assert tools.pending
    assert "公差" in window.status_command.text()
    window.activate_session_document(second.loaded.document.document_id)
    assert session.active is first
    count = len(session.documents)
    window.act_new_drawing.trigger()
    assert len(session.documents) == count
    assert tools.pending


def test_dxf_import_frame_only_commits_to_drawing(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (4, 5))
    target = tmp_path / "frame.dxf"
    write_sketches_dxf((), target, tolerance_frames=(frame,))
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()

    def confirm(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    queue_import = cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])
    queue_import(window, target, unit_override=None)
    qtbot.waitUntil(lambda: services.kernel.drawing_tolerance_frames == (frame,), timeout=10000)
    assert window.loaded_document() is not None


def test_dxf_import_datum_and_frame_preserves_links(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference

    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (5, 5),
    )
    target = tmp_path / "linked.dxf"
    write_sketches_dxf((), target, tolerance_frames=(frame,), datum_identifiers=(datum,))
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    queue_import = cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])
    queue_import(window, target, unit_override=None)
    qtbot.waitUntil(lambda: services.kernel.drawing_tolerance_frames == (frame,), timeout=10000)
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_datum_placement_attaches_to_unambiguous_existing_endpoint(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    editor = window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (1, 2), (15, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_datum()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((3, 10))
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((1, 2))
    )
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.attachment is not None
    assert datum.attachment.sketch_id == sketch.sketch_id
    assert datum.attachment.reference.entity_id == line.entity_id
    assert datum.target_mm == (1, 2)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((4, 9))
    )
    assert tools.handle_command("REATTACH")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((15, 2))
    )
    changed = services.kernel.drawing_datum_identifiers[0]
    assert changed.target_mm == (15, 2)
    assert changed.attachment is not None and changed.attachment.reference.kind == "end"
    assert tools.handle_command("REATTACH")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((8, 2))
    )
    changed = services.kernel.drawing_datum_identifiers[0]
    assert changed.target_mm == (8, 2)
    assert changed.attachment is not None and changed.attachment.reference.kind == "geometry"
    assert changed.attachment.parameter == 0.5
    assert tools.handle_command("MOVE")
    assert tools.handle_command("0,0")
    assert tools.handle_command("2,0")
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.position_mm == (changed.position_mm[0] + 2, changed.position_mm[1])
    assert moved.target_mm == changed.target_mm
    assert moved.attachment == changed.attachment


def test_dxf_import_remaps_attached_datum_if_sketch_id_already_exists(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (1, 2), (8, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (1, 2),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    target = tmp_path / "attached.dxf"
    write_sketches_dxf((sketch,), target, datum_identifiers=(datum,))
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    queue_import = cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])
    queue_import(window, target, unit_override=None)
    qtbot.waitUntil(lambda: len(services.kernel.drawing_datum_identifiers) == 1, timeout=10000)
    imported = services.kernel.drawing_datum_identifiers[0]
    assert imported.attachment is not None
    assert imported.attachment.sketch_id != sketch.sketch_id
    assert services.kernel.datum_attachment_resolved(imported.datum_id)


def test_datum_can_attach_to_polyline_segment(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    from uuid import uuid4

    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_datum()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 10))
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.attachment is not None
    assert datum.attachment.reference.kind == "segment"
    assert datum.attachment.reference.index == 0
    assert datum.attachment.parameter == 0.5


def test_datum_can_attach_to_rectangle_edge(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    from uuid import uuid4

    from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 20))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,)), session_identity=0
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_datum()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 10))
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.attachment is not None
    assert datum.attachment.segment_kind == "rectangle"
    assert datum.attachment.reference.index == 0 and datum.attachment.parameter == 0.5


def test_datum_can_attach_to_spline_interior(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    from uuid import uuid4

    from mycad.core.sketch import Sketch, SplineEntity, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    spline = SplineEntity(uuid4().hex, ((0, 0), (5, 10), (15, 10), (20, 0)))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,)), session_identity=0
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_datum()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 15))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=editor.canvas.local_to_screen(spline.point_at(0.5)),
    )
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.attachment is not None and datum.attachment.curve_kind == "spline"
    assert abs((datum.attachment.parameter or 0) - 0.5) < 0.02


def test_mechanical_spline_datum_f8_first_vertex_is_normal(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import Sketch, SplineEntity, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    spline = SplineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,)), session_identity=0
    )
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    canvas.set_orthogonal_enabled(True)
    tools.begin_mechanical_datum()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 5)))
    assert tools.mechanical_datum_attachment is not None
    assert tools.mechanical_datum_attachment.curve_kind == "spline"
    assert tools.handle_command("V")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 11)))
    assert tools.mechanical_datum_vertices[0] == pytest.approx((7, 8), abs=0.2)
    assert tools.handle_command("30,30")
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.leader_auto_normal and datum.spline_normal_enabled
    assert loaded.document.commands[-1].version == 27


def test_mechanical_spline_datum_warns_when_tangent_is_undefined(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import Sketch, SplineEntity, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    spline = SplineEntity(uuid4().hex, ((0, 0), (0, 0), (5, 5), (10, 0)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_orthogonal_enabled(True)
    tools.begin_mechanical_datum()
    tools.mechanical_datum_target = (0, 0)
    tools.mechanical_datum_attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(spline.entity_id, "geometry"),
        0,
        curve_kind="spline",
        control_count=4,
    )
    assert tools.handle_command("V")
    assert tools.handle_command("1,2")
    assert not tools.mechanical_datum_auto_normal
    assert "无法确定法向" in editor.status_label.text()


def test_spline_self_crossing_produces_ambiguous_hits() -> None:
    from uuid import uuid4

    from mycad.core.sketch import SplineEntity
    from mycad.ui import geometric_tolerance_tools

    spline = SplineEntity(uuid4().hex, ((-1, 0), (2, 3), (-2, 3), (1, 0)))
    find_hits = cast(
        "Callable[[SplineEntity, tuple[float, float], float], tuple[tuple[float, tuple[float, float]], ...]]",
        vars(geometric_tolerance_tools)["_spline_hits"],
    )
    hits = find_hits(spline, (0, 1.287639), 0.01)
    assert len(hits) == 2
    assert hits[0][0] < 0.3 and hits[1][0] > 0.7


def test_radial_reference_dimensions_render_labels_and_are_pickable(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.detached_dimension_layout import layout_reference_dimension
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    for kind, prefix in (("radius", "R"), ("diameter", "⌀")):
        dimension = DetachedDimension(uuid4().hex, kind, (0, 0), (10, 0), (15, 0), 0, 10)
        layout = layout_reference_dimension(dimension, canvas)
        assert layout.text.main.startswith(prefix)
        assert layout.hit(layout.label.center())
        assert len(layout.arrows) == (1 if kind == "radius" else 2)


def test_rotated_ordinate_reference_layout_tracks_axis_and_is_pickable(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.ui.detached_dimension_layout import layout_reference_dimension
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    dimension = DetachedDimension(
        uuid4().hex,
        "ordinate_x",
        (10, 20),
        (14, 23),
        (18, 28),
        90,
        3,
        DimensionTolerance("deviation", 0.1, -0.2, 2),
    )
    layout = layout_reference_dimension(dimension, canvas)
    assert len(layout.lines) == 2
    start, corner = layout.lines[0]
    assert start.y() == pytest.approx(corner.y())
    assert layout.label.height() == pytest.approx(layout.text.width)
    assert layout.label.width() == pytest.approx(layout.text.height)
    assert layout.hit(layout.label.center())
    assert layout.hit((start + corner) / 2)
    direct = DetachedDimension(uuid4().hex, "ordinate_x", (0, 0), (4, 3), (4, 8), 90, 3)
    assert len(layout_reference_dimension(direct, canvas).arrows[0]) == 3


def test_rotated_ordinate_reference_can_be_box_selected_and_undone(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.detached_dimension_layout import layout_reference_dimension

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    qtbot.waitExposed(window)
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    dimension = DetachedDimension(uuid4().hex, "ordinate_x", (0, 0), (4, 3), (8, 8), 90, 3)
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
        session_identity=0,
        imported_reference_dimensions=(dimension,),
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_tool("选择元素")
    bounds = tools.reference_bounds(dimension)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=bounds.center().toPoint())
    assert tools.selected_id == dimension.dimension_id
    tools.selected_ids.clear()
    tools.selected_id = None
    canvas.zoom_view_factor(6)
    arrow = layout_reference_dimension(dimension, canvas).arrows[0]
    point = arrow[0] * 0.1 + arrow[1] * 0.8 + arrow[2] * 0.1
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert tools.selected_id == dimension.dimension_id
    tools.selected_ids.clear()
    tools.selected_id = None
    canvas.zoom_view_factor(1 / 6)
    start, end = canvas.local_to_screen((-10, 20)), canvas.local_to_screen((20, -10))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tools.selected_ids == {dimension.dimension_id}
    assert tools.delete_selected()
    assert not services.kernel.drawing_reference_dimensions
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_reference_dimensions == (dimension,))


@pytest.mark.parametrize("angle", [0, 90])
def test_ordinate_reference_arrow_is_clickable_at_high_zoom(qtbot: QtBot, angle: int) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.detached_dimension_layout import layout_reference_dimension
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.zoom_view_factor(12.0)
    second, base = ((4, 3), (4, 10)) if angle == 0 else ((4, 3), (12, 3))
    dimension = DetachedDimension(
        uuid4().hex, "ordinate_x", (0, 0), second, base, angle, 4 if angle == 0 else 3
    )
    layout = layout_reference_dimension(dimension, canvas)
    arrow = layout.arrows[0]
    point = arrow[0] * 0.1 + arrow[1] * 0.8 + arrow[2] * 0.1
    assert layout.hit(point)


def test_reference_dimension_reports_insufficient_tolerance_precision(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.ui.detached_dimension_layout import layout_reference_dimension
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    dimension = DetachedDimension(
        uuid4().hex,
        "rotated",
        (0, 0),
        (20, 0),
        (0, 5),
        0,
        20,
        DimensionTolerance("symmetric", 1e-10, -1e-10, 8),
    )
    layout = layout_reference_dimension(dimension, canvas)
    assert layout.text.lines == ("公差精度不足",)
    assert layout.hit(layout.label.center())


def test_angular_reference_dimension_renders_and_is_pickable(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.detached_dimension_layout import layout_reference_dimension
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    for kind in ("angular_3p", "angular_2l"):
        dimension = DetachedDimension(
            uuid4().hex, kind, (10, 0), (0, 10), (5, 5), 0, 90, vertex_mm=(0, 0)
        )
        layout = layout_reference_dimension(dimension, canvas)
        assert "90.00°" in layout.text.main
        assert layout.hit(layout.label.center()) and len(layout.lines) == 34


def test_imported_reference_dimension_is_visible_selectable_and_deletable(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    dimension = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
        session_identity=0,
        imported_reference_dimensions=(dimension,),
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    assert dimension in tools.reference_dimensions
    editor.canvas.set_tool("选择元素")
    bounds = tools.reference_bounds(dimension)
    assert not bounds.isEmpty()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 2))
    )
    assert tools.selected_id == dimension.dimension_id
    assert tools.delete_selected()
    assert not services.kernel.drawing_reference_dimensions
    window.request_undo()
    qtbot.waitUntil(
        lambda: services.kernel.drawing_reference_dimensions == (dimension,), timeout=10000
    )


def test_external_dxf_reference_dimension_can_be_imported_and_undone(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    import ezdxf.filemanagement as filemanagement

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    document.modelspace().add_linear_dim(
        base=(0, 5), p1=(0, 0), p2=(10, 0), override={"dimtol": 1, "dimtp": 0.1, "dimtm": 0.2}
    ).render()
    path = tmp_path / "external-reference.dxf"
    document.saveas(path)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", errors.append)
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    queue_import = cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])
    queue_import(window, path, unit_override=None)
    qtbot.waitUntil(lambda: len(services.kernel.drawing_reference_dimensions) == 1, timeout=10000)
    assert not errors
    assert services.kernel.drawing_reference_dimensions[0].nominal == 10
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    qtbot.waitUntil(lambda: len(tools.reference_dimensions) == 1, timeout=10000)
    window.request_undo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_reference_dimensions, timeout=10000)


def test_detached_dimension_edit_move_and_copy(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.dimension_tolerance_editor import DimensionToleranceDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    dimension = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
        session_identity=0,
        imported_reference_dimensions=(dimension,),
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    editor.canvas.set_tool("选择元素")
    label = tools.reference_bounds(dimension).center().toPoint()

    def edit() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DimensionToleranceDialog)
        dialog.editor.mode.setCurrentIndex(dialog.editor.mode.findData("symmetric"))
        dialog.editor.upper_spin.setValue(0.2)
        dialog.accept()

    QTimer.singleShot(20, edit)
    QTest.mouseDClick(editor.canvas, Qt.MouseButton.LeftButton, pos=label)
    edited = services.kernel.drawing_reference_dimensions[0]
    assert edited.tolerance.mode == "symmetric" and edited.tolerance.upper_deviation == 0.2
    assert tools.handle_command("MOVE")
    assert tools.handle_command("0,0")
    assert tools.handle_command("3,4")
    moved = services.kernel.drawing_reference_dimensions[0]
    assert moved.first_mm == (3, 4) and moved.nominal == dimension.nominal
    assert tools.handle_command("COPY")
    assert tools.handle_command("0,0")
    assert tools.handle_command("2,0")
    copied = services.kernel.drawing_reference_dimensions[1]
    assert copied.dimension_id != moved.dimension_id
    assert copied.first_mm == (5, 4) and copied.tolerance == moved.tolerance


def test_frame_rotation_can_be_set_on_create_and_edited(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        if hasattr(dialog, "rotation"):
            dialog.rotation.setValue(30)
            dialog.accept()
        else:
            dialog.reject()

    QTimer.singleShot(20, create)
    tools.begin_frame()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    assert services.kernel.drawing_tolerance_frames
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.rotation_deg == 30

    def edit() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.rotation.setValue(45)
        dialog.accept()

    QTimer.singleShot(20, edit)
    QTest.mouseDClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert services.kernel.drawing_tolerance_frames[0].rotation_deg == 45


def test_frame_layer_can_be_set_and_edited(qtbot: QtBot) -> None:
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        if hasattr(dialog, "layer"):
            dialog.layer.setCurrentText("GDT")
            dialog.accept()
        else:
            dialog.reject()

    QTimer.singleShot(20, create)
    tools.begin_frame()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    assert services.kernel.drawing_tolerance_frames
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.layer_name == "GDT"

    def edit() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.layer.setCurrentText("0")
        dialog.accept()

    QTimer.singleShot(20, edit)
    QTest.mouseDClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert services.kernel.drawing_tolerance_frames[0].layer_name == "0"


def test_frame_clipboard_paste_is_one_undoable_operation(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, create)
    tools.begin_frame()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    frame = services.kernel.drawing_tolerance_frames[0]
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert window.act_copy.isEnabled()
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((40, 10))
    )
    original, pasted = services.kernel.drawing_tolerance_frames
    assert pasted.frame_id != original.frame_id
    assert abs(pasted.position_mm[0] - 40) < 0.2
    assert abs(pasted.position_mm[1] - 10) < 0.2
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_tolerance_frames == (original,), timeout=10000)


@pytest.mark.parametrize("owner", ["frame", "datum", "reference"])
def test_single_annotation_paste_rejects_layer_hidden_before_placement(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    canvas, tools = editor.canvas, editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    if owner == "frame":
        item = FeatureControlFrame(
            uuid4().hex, (ToleranceRow("position", 0.1, 2),), (20, 20), layer_name="GDT"
        )
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [item.to_mapping()]})
        point = tools.screen_bounds(item).center().toPoint()
    elif owner == "datum":
        item = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), layer_name="GDT")
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [item.to_mapping()]})
        point = tools.datum_screen_bounds(item).center().toPoint()
    else:
        item = DetachedDimension(
            uuid4().hex, "rotated", (0, 0), (20, 0), (10, 5), 0, 20, layer_name="GDT"
        )
        assert tools.execute("drawing.reference_dimensions.batch", {"add": [item.to_mapping()]})
        point = tools.reference_bounds(item).center().toPoint()
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    assert canvas.copy_to_clipboard()
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert canvas.begin_clipboard_paste()
    hidden = replace(
        layers,
        layers=tuple(
            replace(layer, visible=False) if layer.name == "GDT" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": hidden.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    count = loaded.document.command_count
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((50, 20)))
    assert loaded.document.command_count == count
    assert "隐藏" in canvas.message
    assert tools.pending
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((50, 20)))
    items = (
        services.kernel.drawing_tolerance_frames
        if owner == "frame"
        else services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_reference_dimensions
    )
    assert len(items) == 2
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            len(
                services.kernel.drawing_tolerance_frames
                if owner == "frame"
                else services.kernel.drawing_datum_identifiers
                if owner == "datum"
                else services.kernel.drawing_reference_dimensions
            )
            == 1
        ),
        timeout=10000,
    )


def test_cross_document_frame_paste_does_not_guess_datum_links(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (10, 10),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert tools.copy_frame_to_clipboard()
    assert tools.begin_frame_paste()
    assert tools.clipboard_frame is not None
    assert tools.clipboard_frame.rows[0].datums[0].datum_id == datum.datum_id
    assert tools.cancel()
    vars(tools)["_clipboard_source"] = uuid4().hex
    assert tools.begin_frame_paste()
    assert tools.clipboard_frame is not None
    assert tools.clipboard_frame.rows[0].datums[0].datum_id is None
    assert "重新建立" in editor.status_label.text()
    assert tools.cancel()


def test_frame_clipboard_detaches_if_source_disappears(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
        leader_attachment=DatumAttachment(
            uuid4().hex, SketchGeometryReference(uuid4().hex, "start")
        ),
    )
    tools.sync((frame,), ())
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert tools.copy_frame_to_clipboard()
    tools.sync((), ())
    assert tools.begin_frame_paste()
    assert tools.clipboard_frame is not None and tools.clipboard_frame.leader_attachment is None
    assert "重新建立" in editor.status_label.text()
    assert tools.cancel()


def test_datum_clipboard_copy_requires_new_label(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    datum = DatumIdentifier(uuid4().hex, "A", (0, 5), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((1, 4))
    )
    assert window.act_copy.isEnabled()
    assert editor.canvas.copy_to_clipboard()
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 5))
    )
    assert len(services.kernel.drawing_datum_identifiers) == 2
    copied = services.kernel.drawing_datum_identifiers[1]
    assert copied.label == "B" and copied.datum_id != datum.datum_id
    assert abs(copied.position_mm[0] - 10) < 0.2


def test_reference_dimension_clipboard_paste_retains_value_and_tolerance(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    dimension = DetachedDimension(
        uuid4().hex,
        "rotated",
        (0, 0),
        (10, 0),
        (0, 5),
        0,
        10,
        DimensionTolerance("symmetric", 0.2, -0.2),
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
        session_identity=0,
        imported_reference_dimensions=(dimension,),
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=tools.reference_bounds(dimension).center().toPoint(),
    )
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((30, 5))
    )
    assert len(services.kernel.drawing_reference_dimensions) == 2
    copied = services.kernel.drawing_reference_dimensions[1]
    assert copied.dimension_id != dimension.dimension_id
    assert copied.nominal == 10 and copied.tolerance == dimension.tolerance
    assert abs(copied.location_mm[0] - 30) < 0.2


def test_copied_attached_datum_tracks_target_changed_before_paste(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 5),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((1, 4))
    )
    assert editor.canvas.copy_to_clipboard()
    moved = replace(sketch, entities=(replace(line, start_mm=(2, 0)),))
    state = moved.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    sync(window)
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((20, 5))
    )
    assert len(services.kernel.drawing_datum_identifiers) == 2
    copied = services.kernel.drawing_datum_identifiers[1]
    assert copied.attachment == datum.attachment
    assert copied.target_mm == (2, 0)


def test_additive_selection_keeps_geometry_datum_and_frame(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, DatumReference
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, source, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 10),
        (0, 0),
        attachment=DatumAttachment(
            source.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (20, 10),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.local_to_screen((1, 9)),
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        tools.screen_bounds(frame).center().toPoint(),
    )
    assert line.entity_id in editor.canvas.selected_entity_ids
    assert tools.selected_ids == {datum.datum_id, frame.frame_id}
    assert editor.canvas.copy_to_clipboard()
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((30, 10))
    )
    assert len(services.kernel.sketches) == 2
    copied_datum = services.kernel.drawing_datum_identifiers[-1]
    copied_frame = services.kernel.drawing_tolerance_frames[-1]
    assert copied_datum.label == "B"
    assert copied_datum.attachment is not None
    assert copied_datum.attachment.sketch_id == services.kernel.sketches[-1].sketch_id
    assert (
        copied_datum.attachment.reference.entity_id
        == services.kernel.sketches[-1].entities[0].entity_id
    )
    assert copied_frame.rows[0].datums[0].datum_id == copied_datum.datum_id
    window.request_undo()
    qtbot.waitUntil(lambda: len(services.kernel.sketches) == 1, timeout=10000)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_cross_document_mixed_copy_remaps_copied_internal_links(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, DatumReference
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    session = DocumentSession()
    window = MainWindow(services=services, document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 10),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (20, 10),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    layers = services.kernel.drawing_layers.add(SketchLayer("UNUSED"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.local_to_screen((1, 9)),
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        tools.screen_bounds(frame).center().toPoint(),
    )
    assert editor.canvas.copy_to_clipboard()
    window.act_new_drawing.trigger()
    target = window.active_sketch_dialog()
    assert target is not None and target is not editor
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((30, 10))
    )
    assert session.active is not None
    target_kernel = session.active.services.kernel
    assert len(target_kernel.sketches) == 1, target.status_label.text()
    assert all(layer.name != "UNUSED" for layer in target_kernel.drawing_layers.layers)
    copied_datum = target_kernel.drawing_datum_identifiers[0]
    copied_frame = target_kernel.drawing_tolerance_frames[0]
    assert copied_datum.attachment is not None
    assert copied_datum.attachment.sketch_id == target_kernel.sketches[0].sketch_id
    assert copied_frame.rows[0].datums[0].datum_id == copied_datum.datum_id
    window.request_undo()
    qtbot.waitUntil(lambda: not target_kernel.sketches, timeout=10000)
    assert (
        not target_kernel.drawing_datum_identifiers and not target_kernel.drawing_tolerance_frames
    )
    window.request_redo()
    qtbot.waitUntil(lambda: len(target_kernel.sketches) == 1, timeout=10000)
    assert target_kernel.drawing_datum_identifiers == (copied_datum,)
    assert target_kernel.drawing_tolerance_frames == (copied_frame,)


def test_mixed_copy_remaps_frame_attachment(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", frame.frame_id, (0, 0)),
    )
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    tools.selected_ids = {frame.frame_id, datum.datum_id}
    tools.selected_id, tools.selected_kind = datum.datum_id, "datum"
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert tools.copy_frame_to_clipboard()
    assert tools.begin_frame_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((40, 40))
    )
    assert len(services.kernel.drawing_datum_identifiers) == 2, editor.status_label.text()
    copied = services.kernel.drawing_datum_identifiers[1]
    assert copied.annotation_attachment is not None
    assert (
        copied.annotation_attachment.object_id
        == services.kernel.drawing_tolerance_frames[1].frame_id
    )
    window.request_undo()
    qtbot.waitUntil(lambda: len(services.kernel.drawing_datum_identifiers) == 1, timeout=10000)


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("styled", [False, True])
def test_single_clipboard_normal_annotation_keeps_vertex_position(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str, styled: bool
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (10, 0),
        attachment=attachment,
        text_style_id="standard" if styled else None,
        leader_offsets=((-3, -4), (-10, -17)),
        leader_auto_normal=True,
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        text_style_id="standard" if styled else None,
        leader_target_mm=(10, 0),
        leader_offsets=((-3, -4), (-10, -17)),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    params: dict[str, object] = (
        {"add_datums": [datum.to_mapping()]}
        if owner == "datum"
        else {"add_frames": [frame.to_mapping()]}
    )
    assert tools.execute("drawing.tolerance.batch", params)
    identity = datum.datum_id if owner == "datum" else frame.frame_id
    tools.selected_id, tools.selected_kind, tools.selected_ids = identity, owner, {identity}
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert tools.copy_frame_to_clipboard()
    assert tools.begin_frame_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((20, -10))
    )
    copied = (
        services.kernel.drawing_datum_identifiers[-1]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[-1]
    )
    assert copied.position_mm == pytest.approx((20, -10)) and copied.leader_auto_normal
    vertices = tuple(
        (copied.position_mm[0] + x, copied.position_mm[1] + y) for x, y in copied.leader_offsets
    )
    assert vertices == ((17, 16), (10, 3))
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            (
                len(services.kernel.drawing_datum_identifiers)
                if owner == "datum"
                else len(services.kernel.drawing_tolerance_frames)
            )
            == 1
        ),
        timeout=10000,
    )


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_cross_document_normal_clipboard_releases_missing_target(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    session = DocumentSession()
    window = MainWindow(services=services, document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (10, 0),
        attachment=attachment,
        leader_offsets=((-10, -17),),
        leader_auto_normal=True,
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(10, 0),
        leader_offsets=((-10, -17),),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    assert tools.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()]}
        if owner == "datum"
        else {"add_frames": [frame.to_mapping()]},
    )
    identity = datum.datum_id if owner == "datum" else frame.frame_id
    tools.selected_id, tools.selected_kind, tools.selected_ids = identity, owner, {identity}
    assert tools.copy_frame_to_clipboard()
    window.act_new_drawing.trigger()
    target = window.active_sketch_dialog()
    assert target is not None and target is not editor
    target_tools = target.canvas.geometric_tolerance_tools
    assert target_tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert target_tools.begin_frame_paste()
    assert "关联" in target.status_label.text()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((30, 30))
    )
    assert session.active is not None
    kernel = session.active.services.kernel
    copied = (
        kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else kernel.drawing_tolerance_frames[0]
    )
    assert not copied.leader_auto_normal
    assert (
        copied.attachment if isinstance(copied, DatumIdentifier) else copied.leader_attachment
    ) is None


def test_single_datum_clipboard_preserves_same_document_attachment(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", frame.frame_id, (0, 0)),
    )
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert tools.copy_frame_to_clipboard()
    assert tools.begin_frame_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((40, 40))
    )
    assert len(services.kernel.drawing_datum_identifiers) == 2, editor.status_label.text()
    copied = services.kernel.drawing_datum_identifiers[1]
    assert copied.annotation_attachment == datum.annotation_attachment
    assert copied.target_mm == datum.target_mm


def test_surface_indication_draws_two_leaders_and_reference(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, SurfaceIndication

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    indication = SurfaceIndication((4, 6), (12, 6), 0.5, ((2, 3),))
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), surface_indication=indication)
    reference, surface, landing = tools.surface_indication_screen_geometry(
        datum.target_mm, indication
    )
    assert reference[0] == editor.canvas.local_to_screen_precise((4, 6))
    assert reference[1] == editor.canvas.local_to_screen_precise((12, 6))
    assert surface[-1] == editor.canvas.local_to_screen_precise((0, 0))
    assert landing == editor.canvas.local_to_screen_precise((8, 6))
    primary, _ = tools.datum_screen_path(datum)
    assert primary[-1] == landing


def test_mechanical_datum_creates_surface_indication(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_mechanical_datum()
    assert tools.handle_command("5,0")
    assert tools.handle_command("F")
    assert tools.handle_command("8,8")
    tools.mechanical_datum_cursor = (20, 20)
    preview = tools.mechanical_datum_preview
    assert preview is not None and preview.surface_indication is not None
    assert tools.handle_command("20,20")
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.target_mm == pytest.approx((5, 0))
    assert datum.surface_indication is not None
    assert datum.surface_indication.reference_start_offset_mm == pytest.approx((3, 8))
    assert datum.attachment is not None and datum.attachment.reference.entity_id == line.entity_id


def test_surface_indication_rejects_duplicate_vertices(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    tools.begin_mechanical_datum()
    for command in ("0,0", "F", "V", "0,0"):
        assert tools.handle_command(command)
    assert tools.surface_vertices == []
    assert tools.surface_joint_pending and tools.surface_vertex_pending
    assert "重合" in editor.status_label.text()


def test_mechanical_datum_creates_bent_surface_indication(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_mechanical_datum()
    for command in ("0,0", "F", "V", "@2,3", "@6,5", "20,20"):
        assert tools.handle_command(command)
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.surface_indication is not None
    assert datum.surface_indication.leader_offsets_mm == ((2, 3),)
    assert datum.surface_indication.reference_start_offset_mm == (8, 8)


def test_mechanical_frame_creates_surface_indication(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    assert tools.handle_command("F")
    assert tools.handle_command("8,8")

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    assert tools.handle_command("20,20")
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.leader_target_mm == (0, 0)
    assert frame.surface_indication is not None
    assert frame.surface_indication.reference_start_offset_mm == (8, 8)
    assert (
        tools.frame_screen_leader(frame)[-1]
        == tools.surface_indication_screen_geometry((0, 0), frame.surface_indication)[2]
    )


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_indication_reference_grip_and_undo(qtbot: QtBot, owner: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, SurfaceIndication

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    surface = SurfaceIndication((5, 5), (10, 5), 0.5, ((3, 3),))
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), surface_indication=surface)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        surface_indication=surface,
    )
    assert tools.execute is not None
    if owner == "datum":
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
        assert (-4, (10, 5)) in cast(
            "Callable[..., tuple[tuple[int, tuple[float, float]], ...]]",
            _private_member(tools, "_datum_grips"),
        )(datum)
        tools.datum_grip = (datum, -4)
        _place_annotation(tools, "datum", (12, 5))
        updated = services.kernel.drawing_datum_identifiers[0].surface_indication
    else:
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
        assert (-4, (10, 5)) in cast(
            "Callable[..., tuple[tuple[int, tuple[float, float]], ...]]",
            _private_member(tools, "_frame_grips"),
        )(frame)
        tools.frame_grip = (frame, -4)
        _place_annotation(tools, "frame", (12, 5))
        updated = services.kernel.drawing_tolerance_frames[0].surface_indication
    assert updated is not None and updated.reference_end_offset_mm == (12, 5)
    window.request_undo()
    if owner == "datum":
        qtbot.waitUntil(
            lambda: services.kernel.drawing_datum_identifiers[0].surface_indication == surface,
            timeout=10000,
        )
    else:
        qtbot.waitUntil(
            lambda: services.kernel.drawing_tolerance_frames[0].surface_indication == surface,
            timeout=10000,
        )


def test_surface_indication_reference_line_respects_frame_text_height(qtbot: QtBot) -> None:
    import math

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance_geometry import datum_triangle

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
        and editor.canvas.text_tools is not None
    )
    styles = TextStyleTable((TextStyle(), TextStyle(style_id="iso", name="ISO", height_mm=7)))
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local")
    editor.canvas.text_tools.sync((), styles)
    tools = editor.canvas.geometric_tolerance_tools
    tools.begin_mechanical_frame()
    for command in ("0,0", "F", "8,8"):
        assert tools.handle_command(command)

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.text_style.setCurrentIndex(dialog.text_style.findData("iso"))
        dialog.accept()

    QTimer.singleShot(20, accept)
    assert tools.handle_command("20,20")
    indication = services.kernel.drawing_tolerance_frames[0].surface_indication
    assert indication is not None
    assert abs(
        indication.reference_end_offset_mm[0] - indication.reference_start_offset_mm[0]
    ) == pytest.approx(10)
    assert indication.arrow_size_mm == pytest.approx(5)
    _, leader, _ = tools.surface_indication_screen_geometry((0, 0), indication)
    expected = datum_triangle(
        (leader[-2].x(), leader[-2].y()),
        (leader[-1].x(), leader[-1].y()),
        min(
            5 * editor.canvas.view_scale,
            math.dist((leader[-2].x(), leader[-2].y()), (leader[-1].x(), leader[-1].y())),
        ),
    )
    path = cast("Callable[..., QPainterPath]", _private_member(tools, "_surface_indication_path"))(
        (0, 0), indication
    )
    assert any(
        (path.elementAt(i).x, path.elementAt(i).y) == pytest.approx(expected[1])
        for i in range(path.elementCount())
    )


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_existing_annotation_switches_surface_and_edge_with_undo(qtbot: QtBot, owner: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
    )
    assert tools.execute is not None
    item = datum if owner == "datum" else frame
    identity = datum.datum_id if owner == "datum" else frame.frame_id
    assert tools.execute(
        "drawing.tolerance.batch",
        {"add_datums" if owner == "datum" else "add_frames": [item.to_mapping()]},
    )
    tools.selected_ids, tools.selected_id, tools.selected_kind = {identity}, identity, owner
    assert tools.handle_command("SURFACEINDICATION")
    assert tools.pending
    assert tools.handle_command("8,8")
    current = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert current.surface_indication is not None
    assert current.surface_indication.reference_start_offset_mm == (8, 8)
    assert tools.handle_command("EDGESYMBOL")
    current = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert current.surface_indication is None
    window.request_undo()
    if owner == "datum":
        qtbot.waitUntil(
            lambda: services.kernel.drawing_datum_identifiers[0].surface_indication is not None,
            timeout=10000,
        )
    else:
        qtbot.waitUntil(
            lambda: services.kernel.drawing_tolerance_frames[0].surface_indication is not None,
            timeout=10000,
        )


def test_surface_indication_edit_preview_and_cancel(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools, canvas = editor.canvas.geometric_tolerance_tools, editor.canvas
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0))
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}
    )
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    assert tools.handle_command("SURFACEINDICATION")
    cast("Callable[..., None]", _private_member(tools, "_datum_pointer_moved"))(
        canvas.local_to_screen((8, 8))
    )
    preview = tools.surface_edit_preview
    assert preview is not None and preview.surface_indication is not None
    assert preview.surface_indication.reference_start_offset_mm == pytest.approx((8, 8), abs=0.2)
    assert tools.cancel()
    assert tools.surface_edit_preview is None
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_surface_indication_edit_menu_and_mouse(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools, canvas = editor.canvas.geometric_tolerance_tools, editor.canvas
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0))
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}
    )
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    menu = next(
        action.menu()
        for action in editor.dimension_toolbar.actions()
        if action.text() == "基准操作"
    )
    assert isinstance(menu, QMenu)
    next(action for action in menu.actions() if action.text() == "添加或重设表面指示…").trigger()
    assert tools.pending
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8, 8)))
    assert services.kernel.drawing_datum_identifiers[0].surface_indication is not None
    next(action for action in menu.actions() if action.text() == "切换为边线指示").trigger()
    assert services.kernel.drawing_datum_identifiers[0].surface_indication is None


def test_surface_indication_edit_respects_orthogonal_mouse(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools, canvas = editor.canvas.geometric_tolerance_tools, editor.canvas
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0))
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}
    )
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    monkeypatch.setattr(canvas, "snap_annotation_point", _unsnapped)
    canvas.set_orthogonal_enabled(True)
    tools.begin_surface_indication_edit()
    assert cast(
        "Callable[..., tuple[float, float]]",
        _private_member(tools, "_constrain_surface_edit_mouse"),
    )((10, 3)) == (10, 0)


def test_surface_indication_edit_rejects_locked_layer(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, SurfaceIndication
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 0),
        layer_name="GDT",
        surface_indication=SurfaceIndication((5, 5), (10, 5), 0.5),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "GDT" else layer for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    assert tools.handle_command("SURFACEINDICATION")
    assert not tools.pending
    assert "解锁" in editor.status_label.text()
    assert tools.handle_command("EDGESYMBOL")
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_surface_indication_edit_rejects_changed_document(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0))
    other = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (50, 50))
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}
    )
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    assert tools.handle_command("SURFACEINDICATION")
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [other.to_mapping()]})
    assert tools.handle_command("8,8")
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert "已变化" in editor.status_label.text()
    assert not tools.pending


def test_surface_indication_grips_preserve_target_and_project_landing() -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    surface = SurfaceIndication((5, 5), (10, 5), 0.5, ((3, 3),))
    moved_start = _surface_grip((0, 0), surface, -3, (4, 5))
    assert moved_start.reference_start_offset_mm == (4, 5)
    moved_landing = _surface_grip((0, 0), surface, -5, (9, 12))
    assert moved_landing.landing_ratio == pytest.approx(0.8)
    moved_vertex = _surface_grip((0, 0), surface, -6, (2, 4))
    assert moved_vertex.leader_offsets_mm == ((2, 4),)
    with pytest.raises(ValueError):
        _surface_grip((0, 0), surface, -4, (5, 5))


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_indication_orthogonal_mouse_uses_last_surface_vertex(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    canvas = editor.canvas
    monkeypatch.setattr(canvas, "snap_annotation_point", _unsnapped)
    canvas.set_orthogonal_enabled(True)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    assert tools.handle_command("F")
    assert tools.handle_command("V")
    assert tools.handle_command("10,10")
    result = (
        cast(
            "Callable[..., tuple[float, float]]", _private_member(tools, "_constrain_datum_mouse")
        )((20, 12))
        if owner == "datum"
        else cast(
            "Callable[..., tuple[float, float]]", _private_member(tools, "_constrain_frame_mouse")
        )((20, 12))
    )
    assert result == (20, 10)


def test_surface_indication_mouse_placement_and_cancel(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    canvas = editor.canvas
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_mechanical_datum()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    assert tools.handle_command("F")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8, 8)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20, 20)))
    assert len(services.kernel.drawing_datum_identifiers) == 1, editor.status_label.text()
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.surface_indication is not None
    assert datum.surface_indication.reference_start_offset_mm == pytest.approx((8, 8), abs=0.2)
    tools.begin_mechanical_datum()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((40, 0)))
    assert tools.handle_command("F")
    assert tools.cancel()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert not tools.surface_joint_pending and not tools.surface_vertices


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_first_vertex_f8_tracks_attachment_normal(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 20))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    canvas, tools = editor.canvas, editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    canvas.set_orthogonal_enabled(True)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    assert tools.handle_command("F")
    assert tools.handle_command("V")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((4, 8)))
    assert tools.surface_vertices[0] == pytest.approx((-2, 2), abs=0.1)
    assert tools.handle_command("5,8")
    if owner == "frame":

        def accept() -> None:
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, GeometricToleranceDialog)
            dialog.accept()

        QTimer.singleShot(20, accept)
    assert tools.handle_command("20,20")
    item = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert item.surface_indication is not None and item.surface_indication.auto_normal
    assert loaded.document.commands[-1].version == 27


def test_surface_normal_grip_releases_only_constrained_vertex() -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    surface = SurfaceIndication((8, 8), (13, 8), 0.5, ((0, 3), (4, 5)), auto_normal=True)
    first = _surface_grip((0, 0), surface, -6, (2, 3))
    other = _surface_grip((0, 0), surface, -7, (5, 5))
    assert not first.auto_normal
    assert other.auto_normal


def test_new_datum_surface_normal_replaces_primary_constraint(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 20))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    editor.canvas.set_orthogonal_enabled(True)
    tools.begin_mechanical_datum()
    for command in ("0,0", "V", "-2,2", "F", "V", "-3,3", "5,8", "20,20"):
        assert tools.handle_command(command)
    datum = services.kernel.drawing_datum_identifiers[0]
    assert not datum.leader_auto_normal
    assert datum.surface_indication is not None and datum.surface_indication.auto_normal
    assert datum.surface_indication.leader_offsets_mm == ((-3, 3),)
    assert datum.leader_offsets == ((-22, -18),)


def test_detach_datum_releases_surface_normal(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, SurfaceIndication
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (10, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
        ),
        surface_indication=SurfaceIndication((5, 8), (10, 8), 0.5, ((0, 3),), auto_normal=True),
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        datum.datum_id,
        "datum",
        {datum.datum_id},
    )
    tools.detach_selected_datum()
    detached = services.kernel.drawing_datum_identifiers[0]
    assert detached.attachment is None
    assert detached.surface_indication is not None and not detached.surface_indication.auto_normal
    assert detached.surface_indication.leader_offsets_mm == ((0, 3),)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


@pytest.mark.parametrize("action", ["grip", "MOVE", "COPY"])
def test_frame_normal_movement_keeps_vertex_side(qtbot: QtBot, action: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(target.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(10, 0),
        leader_offsets=((-3, -4), (-10, -17)),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    if action == "grip":
        tools.frame_grip = (frame, -1)
        _place_annotation(tools, "frame", (20, -10))
    else:
        assert tools.handle_command(action)
        assert tools.handle_command("0,0")
        assert tools.handle_command("0,-30")
    moved = services.kernel.drawing_tolerance_frames[-1]
    assert moved.position_mm == (20, -10) and moved.leader_auto_normal
    vertices = tuple(
        (moved.position_mm[0] + x, moved.position_mm[1] + y) for x, y in moved.leader_offsets
    )
    assert vertices == ((17, 16), (10, 3))
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_tolerance_frames == (frame,), timeout=10000)


def test_frame_normal_vertex_grip_releases_only_constrained_vertex() -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "geometry"), 0.5)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(10, 0),
        leader_offsets=((-3, -4), (-10, -17)),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    other = _frame_grip_value(frame, 0, (18, 16))
    last = _frame_grip_value(frame, 1, (12, 3))
    assert other.leader_auto_normal
    assert not last.leader_auto_normal


def test_frame_f8_primary_leader_is_normal(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 20))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    canvas, tools = editor.canvas, editor.canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_orthogonal_enabled(True)
    tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    assert tools.handle_command("V")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((4, 8)))
    assert tools.mechanical_frame_vertices[0] == pytest.approx((-2, 2))

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    assert tools.handle_command("20,20")
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.leader_auto_normal
    assert loaded.document.commands[-1].version == 27


def test_frame_surface_normal_to_edge_preserves_constraint(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
        ),
        surface_indication=SurfaceIndication((5, 8), (10, 8), 0.5, ((0, 3),), auto_normal=True),
    )
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    tools.remove_surface_indication()
    result = services.kernel.drawing_tolerance_frames[0]
    assert result.surface_indication is None
    assert result.leader_offsets == ((-20, -17),)
    assert result.leader_auto_normal
    assert "约束已解除" not in editor.status_label.text()
    qtbot.waitUntil(lambda: result in tools.frames, timeout=10000)
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    tools.begin_surface_indication_edit()
    cast("Callable[..., None]", _private_member(tools, "_finish_surface_indication_edit"))((5, 8))
    restored = services.kernel.drawing_tolerance_frames[0]
    assert not restored.leader_auto_normal
    assert restored.surface_indication is not None and restored.surface_indication.auto_normal
    assert restored.surface_indication.leader_offsets_mm == ((0, 3),)


def test_switching_datum_to_surface_preserves_normal_vertex_and_undo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (10, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
        ),
        leader_offsets=((-10, -17),),
        leader_auto_normal=True,
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        datum.datum_id,
        "datum",
        {datum.datum_id},
    )
    tools.begin_surface_indication_edit()
    cast("Callable[..., None]", _private_member(tools, "_finish_surface_indication_edit"))((15, 8))
    converted = services.kernel.drawing_datum_identifiers[0]
    assert not converted.leader_auto_normal
    assert converted.surface_indication is not None and converted.surface_indication.auto_normal
    assert converted.surface_indication.leader_offsets_mm[0] == pytest.approx((0, 3))
    assert not converted.leader_offsets
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)
    window.request_redo()
    qtbot.waitUntil(
        lambda: services.kernel.drawing_datum_identifiers == (converted,), timeout=10000
    )
    qtbot.waitUntil(lambda: converted in tools.datums, timeout=10000)
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        datum.datum_id,
        "datum",
        {datum.datum_id},
    )
    tools.remove_surface_indication()
    edge = services.kernel.drawing_datum_identifiers[0]
    assert edge.surface_indication is None and edge.leader_auto_normal, editor.status_label.text()
    assert edge.leader_offsets == datum.leader_offsets


def test_surface_indication_reference_crossing_selection(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, SurfaceIndication

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (50, 50),
        (0, 0),
        surface_indication=SurfaceIndication((4, 6), (20, 6), 0.9),
    )
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}
    )
    point = editor.canvas.local_to_screen_precise((7, 6))
    tools.select_box(point + QPointF(3, -3), point + QPointF(-3, 3), Qt.KeyboardModifier.NoModifier)
    assert datum.datum_id in tools.selected_ids


def test_mechanical_datum_creates_surface_extension_with_keyword(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_mechanical_datum()
    assert tools.handle_command("E")
    assert tools.handle_command("15,0")
    assert tools.handle_command("20,20")
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.attachment is not None and datum.attachment.surface_extension is not None
    assert datum.target_mm == pytest.approx((15, 0))


def test_mechanical_frame_creates_surface_extension_with_keyword(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools.begin_mechanical_frame()
    assert tools.handle_command("E") and tools.handle_command("15,0")

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    assert tools.handle_command("30,25")
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.leader_attachment is not None
    assert frame.leader_attachment.surface_extension is not None
    assert frame.leader_target_mm == pytest.approx((15, 0))


@pytest.mark.parametrize("kind", ["datum", "frame"])
def test_toolbar_surface_extension_with_command_bar_and_mouse(qtbot: QtBot, kind: str) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    (window.act_datum_label if kind == "datum" else window.act_geometric_tolerance).trigger()
    bar = editor.drawing_command_bar.input
    bar.setFocus()
    QTest.keyClicks(bar, "E")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert tools.surface_pick_active
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, 0)))
    assert not tools.surface_pick_active

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        if kind == "datum":
            assert isinstance(dialog, QInputDialog)
            dialog.setTextValue("A")
        else:
            assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20, 20)))
    if kind == "datum":
        item = services.kernel.drawing_datum_identifiers[0]
        attachment, target = item.attachment, item.target_mm
    else:
        item_frame = services.kernel.drawing_tolerance_frames[0]
        attachment, target = item_frame.leader_attachment, item_frame.leader_target_mm
    assert attachment is not None and attachment.reference.entity_id == line.entity_id
    assert attachment.surface_extension is not None
    assert attachment.surface_extension.side == "end"
    assert target == pytest.approx((15, 0), abs=0.2)


def test_surface_extension_picks_clockwise_arc(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import ArcEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 90, -90)
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,)), session_identity=0
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    attachment, target = cast(
        "Callable[..., tuple[DatumAttachment | None, tuple[float, float]]]",
        _private_member(tools, "_pick_surface_extension"),
    )((9.8480775301, -1.7364817767))
    assert attachment is not None and attachment.surface_extension is not None
    assert attachment.surface_extension.side == "end"
    assert target == pytest.approx((9.8480775301, -1.7364817767))
    assert len(tools.surface_screen_path(attachment)) > 2


def test_surface_extension_rejects_ambiguous_overlapping_targets(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    lines = tuple(LineEntity(uuid4().hex, (0, 0), (10, 0)) for _ in range(2))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines), session_identity=0
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools.begin_mechanical_datum()
    tools.handle_command("E")
    tools.handle_command("15,0")
    assert tools.mechanical_datum_target is None
    assert "不唯一" in editor.status_label.text()


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_extension_target_grip_preserves_style(qtbot: QtBot, owner: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (15, 0), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(15, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
    )
    assert tools.execute is not None
    if owner == "datum":
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
        tools.datum_grip = (datum, -2)
        _place_annotation(tools, "datum", (18, 0))
        updated = services.kernel.drawing_datum_identifiers[0]
        new_attachment = updated.attachment
        assert updated.target_mm == pytest.approx((18, 0))
    else:
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
        tools.frame_grip = (frame, -2)
        _place_annotation(tools, "frame", (18, 0))
        updated_frame = services.kernel.drawing_tolerance_frames[0]
        new_attachment = updated_frame.leader_attachment
        assert updated_frame.leader_target_mm == pytest.approx((18, 0))
    assert new_attachment is not None and new_attachment.surface_extension is not None
    assert new_attachment.surface_extension.distance_mm == pytest.approx(8)
    assert new_attachment.surface_extension.offset_mm == 1
    assert new_attachment.surface_extension.overshoot_mm == 2
    window.request_undo()
    if owner == "datum":
        qtbot.waitUntil(
            lambda: services.kernel.drawing_datum_identifiers[0].target_mm == datum.target_mm,
            timeout=10000,
        )
    else:
        qtbot.waitUntil(
            lambda: (
                services.kernel.drawing_tolerance_frames[0].leader_target_mm
                == frame.leader_target_mm
            ),
            timeout=10000,
        )


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_extension_edit_settings_are_undoable(qtbot: QtBot, owner: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.geometric_tolerance_dialog import SurfaceExtensionDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (15, 0), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(15, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools.execute is not None
    item = datum if owner == "datum" else frame
    assert tools.execute(
        "drawing.tolerance.batch",
        {"add_datums" if owner == "datum" else "add_frames": [item.to_mapping()]},
    )
    identity = datum.datum_id if owner == "datum" else frame.frame_id
    tools.selected_ids, tools.selected_id, tools.selected_kind = {identity}, identity, owner

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, SurfaceExtensionDialog)
        dialog.offset.setValue(1.5)
        dialog.overshoot.setValue(3)
        dialog.accept()

    QTimer.singleShot(20, accept)
    if owner == "datum":
        assert tools.handle_command("SURFACEEXTEDIT")
    else:
        menu = next(
            action.menu()
            for action in editor.dimension_toolbar.actions()
            if action.text() == "基准操作"
        )
        assert isinstance(menu, QMenu)
        action = next(action for action in menu.actions() if action.text() == "编辑表面延伸线…")
        action.trigger()
    changed = (
        services.kernel.drawing_datum_identifiers[0].attachment
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0].leader_attachment
    )
    assert changed is not None and changed.surface_extension is not None
    assert changed.surface_extension.offset_mm == 1.5
    assert changed.surface_extension.overshoot_mm == 3
    window.request_undo()
    if owner == "datum":
        qtbot.waitUntil(
            lambda: services.kernel.drawing_datum_identifiers[0].attachment == attachment,
            timeout=10000,
        )
    else:
        qtbot.waitUntil(
            lambda: services.kernel.drawing_tolerance_frames[0].leader_attachment == attachment,
            timeout=10000,
        )


def test_surface_extension_dialog_preserves_precision_and_rejects_bad_exact_input(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialog

    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.ui.geometric_tolerance_dialog import SurfaceExtensionDialog

    original = SurfaceExtensionSpec("end", 10, 0.123456789123, 2)
    dialog = SurfaceExtensionDialog(original)
    qtbot.addWidget(dialog)
    assert dialog.value() == original
    monkeypatch.setattr(QInputDialog, "getText", _text_response("bad"))
    cast("Callable[..., None]", _private_member(dialog, "_exact"))(dialog.offset, "间隙")
    dialog.accept()
    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QInputDialog, "getText", _text_response("0.123456789124"))
    cast("Callable[..., None]", _private_member(dialog, "_exact"))(dialog.offset, "间隙")
    dialog.accept()
    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    assert dialog.value().offset_mm == 0.123456789124


def test_surface_extension_dialog_rejects_invalid_geometry(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QDialog

    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.ui.geometric_tolerance_dialog import SurfaceExtensionDialog

    dialog = SurfaceExtensionDialog(SurfaceExtensionSpec("end", 5, 1, 2))
    qtbot.addWidget(dialog)
    dialog.offset.setValue(8)
    dialog.accept()
    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert "间隙" in dialog.message.text()


def test_datum_surface_extension_is_drawable_and_selectable(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (15, 0), attachment=attachment)
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}
    )
    points = tools.surface_screen_path(attachment)
    assert len(points) >= 2
    assert points[0] == editor.canvas.local_to_screen_precise((11, 0))
    assert points[-1] == editor.canvas.local_to_screen_precise((17, 0))
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((12, 0))
    )
    assert datum.datum_id in tools.selected_ids


def test_single_frame_clipboard_preserves_same_document_attachment(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import AnnotationAttachment

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    rows = (ToleranceRow("position", 0.1, 2),)
    source = FeatureControlFrame(uuid4().hex, rows, (0, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        rows,
        (20, 20),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        leader_annotation_attachment=AnnotationAttachment("frame", source.frame_id, (0, 0)),
    )
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch", {"add_frames": [source.to_mapping(), frame.to_mapping()]}
    )
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {frame.frame_id},
        frame.frame_id,
        "frame",
    )
    assert tools.copy_frame_to_clipboard()
    assert tools.begin_frame_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((40, 40))
    )
    assert len(services.kernel.drawing_tolerance_frames) == 3, editor.status_label.text()
    copied = services.kernel.drawing_tolerance_frames[2]
    assert copied.leader_annotation_attachment == frame.leader_annotation_attachment
    assert copied.leader_target_mm == frame.leader_target_mm


def test_single_datum_clipboard_cross_document_detaches_external_annotation(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", frame.frame_id, (0, 0)),
    )
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert tools.copy_frame_to_clipboard()
    vars(tools)["_clipboard_source"] = uuid4().hex
    assert tools.begin_frame_paste()
    assert tools.clipboard_datum is not None
    assert tools.clipboard_datum.annotation_attachment is None
    assert "重新建立" in editor.status_label.text()


def test_cross_document_mixed_copy_remaps_frame_attachment(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    services = app.build_app(discoverers=())
    session = DocumentSession()
    window = MainWindow(services=services, document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    source_editor = window.active_sketch_dialog()
    assert source_editor is not None and source_editor.canvas.geometric_tolerance_tools is not None
    tools = source_editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", frame.frame_id, (0, 0)),
    )
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {frame.frame_id, datum.datum_id},
        datum.datum_id,
        "datum",
    )
    assert tools.copy_frame_to_clipboard()
    window.act_new_drawing.trigger()
    target = window.active_sketch_dialog()
    assert target is not None and target is not source_editor
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((30, 30))
    )
    assert session.active is not None
    kernel = session.active.services.kernel
    assert len(kernel.drawing_datum_identifiers) == 1, target.status_label.text()
    copied = kernel.drawing_datum_identifiers[0]
    assert copied.annotation_attachment is not None
    assert copied.annotation_attachment.object_id == kernel.drawing_tolerance_frames[0].frame_id


@pytest.mark.parametrize("rotated_ordinate", [False, True])
def test_mixed_copy_remaps_reference_dimension_attachment(
    qtbot: QtBot, monkeypatch: MonkeyPatch, rotated_ordinate: bool
) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    dimension = (
        DetachedDimension(uuid4().hex, "ordinate_y", (0, 0), (4, 3), (0, 5), 90, -4)
        if rotated_ordinate
        else DetachedDimension(uuid4().hex, "aligned", (0, 0), (10, 0), (0, 5), 0, 10)
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 5),
        annotation_attachment=AnnotationAttachment(
            "reference_dimension", dimension.dimension_id, (0, 0)
        ),
    )
    assert tools.execute is not None
    assert tools.execute("drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]})
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {dimension.dimension_id, datum.datum_id},
        datum.datum_id,
        "datum",
    )
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert tools.copy_frame_to_clipboard()
    assert tools.begin_frame_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((40, 40))
    )
    assert len(services.kernel.drawing_datum_identifiers) == 2, editor.status_label.text()
    copied = services.kernel.drawing_datum_identifiers[1]
    assert copied.annotation_attachment is not None
    assert (
        copied.annotation_attachment.object_id
        == services.kernel.drawing_reference_dimensions[1].dimension_id
    )
    copied_dimension = services.kernel.drawing_reference_dimensions[1]
    assert copied_dimension.angle_deg == dimension.angle_deg
    assert copied_dimension.nominal == dimension.nominal


def test_mixed_copy_remaps_sketch_dimension_attachment(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=20,
        unit="mm",
        position_mm=(0, 5),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 5),
        annotation_attachment=AnnotationAttachment(
            "sketch_dimension", dim.constraint_id, (0, 0), sketch.sketch_id
        ),
    )
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert tools.copy_frame_to_clipboard()
    assert tools.begin_frame_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((40, 40))
    )
    assert len(services.kernel.drawing_datum_identifiers) == 2, editor.status_label.text()
    copied = services.kernel.drawing_datum_identifiers[1]
    assert copied.annotation_attachment is not None
    assert copied.annotation_attachment.sketch_id != sketch.sketch_id
    assert copied.annotation_attachment.object_id != dim.constraint_id
    copied_sketch = next(
        s for s in services.kernel.sketches if s.sketch_id == copied.annotation_attachment.sketch_id
    )
    assert any(
        c.constraint_id == copied.annotation_attachment.object_id for c in copied_sketch.constraints
    )


def test_mixed_clipboard_preserves_surface_indication_and_undo(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, SurfaceIndication
    from mycad.core.geometric_tolerance_geometry import surface_indication_geometry
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    indication = SurfaceIndication((3, 8), (8, 8), 0.5, ((1, 4),))
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 20), (10, 0), attachment=attachment, surface_indication=indication
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert tools.copy_frame_to_clipboard() and tools.begin_frame_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((40, 40))
    )
    assert len(services.kernel.drawing_datum_identifiers) == 2, editor.status_label.text()
    copied = services.kernel.drawing_datum_identifiers[1]
    assert copied.attachment is not None and copied.attachment.reference.entity_id != line.entity_id
    assert copied.surface_indication == indication
    assert surface_indication_geometry(copied.target_mm, indication)[0][0] == pytest.approx(
        (copied.target_mm[0] + 3, copied.target_mm[1] + 8)
    )
    window.request_undo()
    qtbot.waitUntil(lambda: len(services.kernel.drawing_datum_identifiers) == 1, timeout=10000)


def test_cross_document_mixed_clipboard_rebinds_surface_indication(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, SurfaceIndication
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    session = DocumentSession()
    window = MainWindow(services=services, document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    assert session.active is not None
    source_services = session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(source_services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    indication = SurfaceIndication((3, 8), (8, 8), 0.5, ((1, 4),))
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 20), (10, 0), attachment=attachment, surface_indication=indication
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools.execute is not None and tools.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    assert tools.copy_frame_to_clipboard()
    window.act_new_drawing.trigger()
    target = window.active_sketch_dialog()
    assert target is not None and target is not editor
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((40, 40))
    )
    assert session.active is not None
    kernel = session.active.services.kernel
    assert len(kernel.drawing_datum_identifiers) == 1, target.status_label.text()
    copied = kernel.drawing_datum_identifiers[0]
    assert copied.surface_indication == indication
    assert copied.attachment is not None and copied.attachment.reference.entity_id != line.entity_id
    assert any(
        copied.attachment.reference.entity_id == item.entity_id
        for s in kernel.sketches
        for item in s.entities
    )


def test_mixed_copy_keeps_reference_to_same_document_uncopied_datum(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    datum = DatumIdentifier(uuid4().hex, "A", (0, 10), (0, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (20, 10),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        tools.screen_bounds(frame).center().toPoint(),
    )
    assert tools.handle_command("COPY")
    assert tools.handle_command("0,0")
    assert tools.handle_command("20,0")
    assert len(services.kernel.sketches) == 2
    assert services.kernel.drawing_tolerance_frames[-1].rows[0].datums[0].datum_id == datum.datum_id
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("select_dimension", [False, True])
def test_mixed_copy_preserves_fully_selected_geometry_constraints(
    qtbot: QtBot, select_dimension: bool
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, -10),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (20, 10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.geometric_tolerance_tools.screen_bounds(frame).center().toPoint(),
    )
    assert line.entity_id in editor.canvas.selected_entity_ids
    if select_dimension:
        editor.canvas.selected_constraint_ids = {constraint.constraint_id}
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((40, 10))
    )
    assert len(services.kernel.sketches) == 2
    copied = services.kernel.sketches[-1]
    assert len(copied.constraints) == 1
    assert copied.constraints[0].references[0].entity_id == copied.entities[0].entity_id
    assert copied.constraints[0].value == 20


def test_mixed_paste_stops_if_target_document_changes(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (20, 10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        tools.screen_bounds(frame).center().toPoint(),
    )
    assert editor.canvas.copy_to_clipboard() and editor.canvas.begin_clipboard_paste()
    extra = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.2, 1),), (30, 20))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [extra.to_mapping()]}, "local")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((40, 10))
    )
    assert len(services.kernel.sketches) == 1
    assert len(services.kernel.drawing_tolerance_frames) == 2
    assert "图纸已变化" in editor.status_label.text()


def test_mixed_copy_rejects_constraint_with_unselected_geometry(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (10, 0), (20, 0))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (relation,)),
        session_identity=0,
    )
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (20, 10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.geometric_tolerance_tools.screen_bounds(frame).center().toPoint(),
    )
    assert not editor.canvas.copy_to_clipboard()
    assert "全部图元" in editor.status_label.text()


def test_mixed_copy_preserves_named_dimension_style(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    style = DimensionStyle("检验", linear_tolerance=DimensionTolerance("symmetric", 0.1, -0.1))
    table = DimensionStyleTable((DimensionStyle("标准"), style), "标准")
    loaded.bus.execute("drawing.dimension_styles.set", table.to_mapping(), "local")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        style_name="检验",
        position_mm=(10, -10),
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint,)),
        session_identity=0,
    )
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (20, 10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.geometric_tolerance_tools.screen_bounds(frame).center().toPoint(),
    )
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((40, 10))
    )
    assert len(services.kernel.sketches) == 2
    copied = services.kernel.sketches[-1].constraints[0]
    assert copied.style_name == "检验"
    assert (
        services.kernel.drawing_dimension_styles.get(copied.style_name).linear_tolerance
        == style.linear_tolerance
    )


def test_same_document_frame_copy_reuses_text_style(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    styles = TextStyleTable((TextStyle(), TextStyle("inspect", "字体", height_mm=7)))
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local")
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (20, 10), text_style_id="inspect"
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((40, 10))
    )
    assert len(services.kernel.drawing_tolerance_frames) == 2
    assert services.kernel.drawing_tolerance_frames[1].text_style_id == "inspect"
    assert services.kernel.drawing_text_styles == styles


def test_clipboard_rejects_styled_frame_without_style_definition(qtbot: QtBot) -> None:
    import json
    from uuid import uuid4

    from PySide6.QtCore import QMimeData

    from mycad.ui.geometric_tolerance_tools import TOLERANCE_CLIPBOARD_MIME

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (0, 0), text_style_id="inspect"
    )
    mime = QMimeData()
    mime.setData(
        TOLERANCE_CLIPBOARD_MIME,
        json.dumps(
            {
                "format": "mycad-tolerance-annotation",
                "version": 1,
                "source": "foreign",
                "kind": "frame",
                "object": frame.to_mapping(),
            }
        ).encode(),
    )
    QApplication.clipboard().setMimeData(mime)
    assert editor.canvas.begin_clipboard_paste()
    assert editor.canvas.geometric_tolerance_tools.clipboard_frame is None
    assert "文字样式" in editor.status_label.text()


@pytest.mark.parametrize("mixed", [False, True])
def test_cross_document_datum_copy_preserves_conflicting_text_style(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    mixed: bool,
) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    session = DocumentSession()
    window = MainWindow(services=services, document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    source_style = TextStyle("inspect", "字体", "Font A", height_mm=7)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), source_style)).to_mapping(), "local"
    )
    if mixed:
        line = LineEntity(uuid4().hex, (0, 0), (20, 0))
        app.commit_new_sketch(
            services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
        )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (20, 0), text_style_id="inspect")
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    if mixed:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
        )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier if mixed else Qt.KeyboardModifier.NoModifier,
        tools.datum_screen_bounds(datum).center().toPoint(),
    )
    assert editor.canvas.copy_to_clipboard()
    window.act_new_drawing.trigger()
    target, target_loaded = window.active_sketch_dialog(), window.loaded_document()
    assert target is not None and target_loaded is not None and session.active is not None
    target_kernel = session.active.services.kernel
    target_style = TextStyle("inspect", "字体", "Font B", height_mm=3)
    target_loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), target_style)).to_mapping(), "local"
    )
    sync(window)
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((40, 10))
    )
    pasted = target_kernel.drawing_datum_identifiers[0]
    assert (
        pasted.label == "B"
        and pasted.text_style_id is not None
        and pasted.text_style_id != "inspect"
    )
    assert target_kernel.drawing_text_styles.get(pasted.text_style_id).font_family == "Font A"
    assert target_kernel.drawing_text_styles.get("inspect") == target_style
    target_loaded.bus.undo_operation()
    assert not target_kernel.drawing_datum_identifiers
    target_loaded.bus.redo_operation()
    assert target_kernel.drawing_datum_identifiers[0].text_style_id == pasted.text_style_id


@pytest.mark.parametrize("mixed", [False, True])
def test_cross_document_frame_copy_preserves_conflicting_text_style(
    qtbot: QtBot, mixed: bool
) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    session = DocumentSession()
    window = MainWindow(services=services, document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    source_style = TextStyle("inspect", "字体", "Font A", height_mm=7)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), source_style)).to_mapping(), "local"
    )
    if mixed:
        line = LineEntity(uuid4().hex, (0, 0), (20, 0))
        app.commit_new_sketch(
            services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
        )
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (20, 10), text_style_id="inspect"
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    if mixed:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
        )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier if mixed else Qt.KeyboardModifier.NoModifier,
        tools.screen_bounds(frame).center().toPoint(),
    )
    assert editor.canvas.copy_to_clipboard()
    window.act_new_drawing.trigger()
    target, target_loaded = window.active_sketch_dialog(), window.loaded_document()
    assert target is not None and target_loaded is not None and session.active is not None
    target_kernel = session.active.services.kernel
    target_style = TextStyle("inspect", "字体", "Font B", height_mm=3)
    target_loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), target_style)).to_mapping(), "local"
    )
    sync(window)
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((40, 10))
    )
    pasted = target_kernel.drawing_tolerance_frames[0]
    assert pasted.text_style_id is not None and pasted.text_style_id != "inspect"
    assert target_kernel.drawing_text_styles.get(pasted.text_style_id).font_family == "Font A"
    assert target_kernel.drawing_text_styles.get("inspect") == target_style
    target_loaded.bus.undo_operation()
    assert not target_kernel.drawing_tolerance_frames
    assert target_kernel.drawing_text_styles.get("inspect") == target_style
    target_loaded.bus.redo_operation()
    assert target_kernel.drawing_tolerance_frames[0].text_style_id == pasted.text_style_id


def test_cross_document_mixed_copy_renames_conflicting_dimension_style(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    session = DocumentSession()
    window = MainWindow(services=services, document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    source_text_styles = TextStyleTable((TextStyle(), TextStyle("inspect", "字体", "Font A")))
    loaded.bus.execute("drawing.text_styles.set", source_text_styles.to_mapping(), "local")
    source_style = DimensionStyle(
        "检验", linear_tolerance=DimensionTolerance("symmetric", 0.1, -0.1), text_style_id="inspect"
    )
    loaded.bus.execute(
        "drawing.dimension_styles.set",
        DimensionStyleTable((DimensionStyle("标准"), source_style), "标准").to_mapping(),
        "local",
    )
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        style_name="检验",
        position_mm=(10, -10),
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint,)),
        session_identity=0,
    )
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (20, 10), text_style_id="inspect"
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    note = DrawingText(uuid4().hex, "note", (5, 15), style_id="inspect")
    loaded.bus.execute("drawing.text.batch", {"add": [note.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.geometric_tolerance_tools.screen_bounds(frame).center().toPoint(),
    )
    assert editor.canvas.text_tools is not None
    editor.canvas.text_tools.selected_ids = {note.text_id}
    assert editor.canvas.copy_to_clipboard()
    window.act_new_drawing.trigger()
    target = window.active_sketch_dialog()
    target_loaded = window.loaded_document()
    assert target is not None and target_loaded is not None and session.active is not None
    target_kernel = session.active.services.kernel
    target_text_styles = TextStyleTable((TextStyle(), TextStyle("inspect", "字体", "Font B")))
    target_loaded.bus.execute("drawing.text_styles.set", target_text_styles.to_mapping(), "local")
    destination_style = DimensionStyle(
        "检验", linear_tolerance=DimensionTolerance("symmetric", 0.2, -0.2)
    )
    target_loaded.bus.execute(
        "drawing.dimension_styles.set",
        DimensionStyleTable((DimensionStyle("标准"), destination_style), "标准").to_mapping(),
        "local",
    )
    target_layers = target_kernel.drawing_layers
    target_layers = replace(
        target_layers,
        layers=tuple(
            replace(layer, color_rgb=(200, 0, 0)) if layer.name == "0" else layer
            for layer in target_layers.layers
        ),
    )
    target_loaded.bus.execute(
        "drawing.layers.set",
        {"layers": target_layers.to_mapping(), "dimension_layer": "DIM"},
        "local",
    )
    sync(window)
    assert target.canvas.begin_clipboard_paste()
    assert target.canvas.geometric_tolerance_tools is not None
    assert target.canvas.geometric_tolerance_tools.clipboard_mixed is not None, (
        target.status_label.text()
    )
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((40, 10))
    )
    assert len(target_kernel.sketches) == 1, target.status_label.text()
    assert "同名图层采用目标属性：0" in target.status_label.text()
    copied = target_kernel.sketches[0].constraints[0]
    assert copied.style_name is not None and copied.style_name != "检验"
    assert (
        target_kernel.drawing_dimension_styles.get(copied.style_name).linear_tolerance
        == source_style.linear_tolerance
    )
    copied_font = target_kernel.drawing_dimension_styles.get(copied.style_name).text_style_id
    assert copied_font is not None and copied_font != "inspect"
    assert target_kernel.drawing_tolerance_frames[0].text_style_id == copied_font
    assert target_kernel.drawing_texts[0].style_id == copied_font
    assert target_kernel.drawing_text_styles.get(copied_font).font_family == "Font A"
    assert target_kernel.drawing_text_styles.get("inspect").font_family == "Font B"
    assert (
        target_kernel.drawing_dimension_styles.get("检验").linear_tolerance
        == destination_style.linear_tolerance
    )
    window.request_undo()
    qtbot.waitUntil(lambda: not target_kernel.sketches, timeout=10000)
    assert target_kernel.drawing_text_styles == target_text_styles
    window.request_redo()
    qtbot.waitUntil(lambda: len(target_kernel.sketches) == 1, timeout=10000)
    assert target_kernel.drawing_text_styles.get(copied_font).font_family == "Font A"


@pytest.mark.parametrize("with_dimension", [False, True])
def test_mixed_move_command_moves_geometry_and_annotations_atomically(
    qtbot: QtBot, with_dimension: bool
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, DatumReference
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, -10),
    )
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint,) if with_dimension else ()
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 10),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (20, 10),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.local_to_screen((1, 9)),
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        tools.screen_bounds(frame).center().toPoint(),
    )
    if with_dimension:
        editor.canvas.selected_constraint_ids = {constraint.constraint_id}
    assert tools.handle_command("MOVE")
    assert tools.handle_command("0,0")
    assert tools.handle_command("5,3")
    moved_line = services.kernel.sketches[0].entities[0]
    assert isinstance(moved_line, LineEntity)
    assert moved_line.start_mm == (5, 3)
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (5, 3)
    assert services.kernel.drawing_tolerance_frames[0].position_mm == (25, 13)
    if with_dimension:
        assert services.kernel.sketches[0].constraints[0].position_mm == (15, -7)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.sketches == (sketch,), timeout=10000)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_ordinate_reference_dimension_negative_value_renders_and_is_pickable(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.detached_dimension_layout import layout_reference_dimension
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    for kind, second in (("ordinate_x", (-10, 0)), ("ordinate_y", (0, -10))):
        dimension = DetachedDimension(uuid4().hex, kind, (0, 0), second, (5, 5), 0, -10)
        layout = layout_reference_dimension(dimension, canvas)
        assert "-10.00" in layout.text.main
        assert layout.hit(layout.label.center()) and len(layout.arrows) == 1


@pytest.mark.parametrize("part", ["box", "leader", "triangle"])
def test_datum_parts_can_be_selected_and_deleted(
    qtbot: QtBot, monkeypatch: MonkeyPatch, part: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    window.activateWindow()
    qtbot.waitUntil(lambda: window.isActiveWindow(), timeout=10000)
    editor.drawing_command_bar.input.setFocus()
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_datum()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 15)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, -15)))
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum in tools.datums, (tools.datums, canvas.tool)
    if part == "box":
        point = tools.datum_screen_bounds(datum).center().toPoint()
    else:
        segment, triangle = tools.datum_screen_leader(datum)
        assert segment is not None and triangle
        point = (
            ((segment[0] + segment[1]) / 2).toPoint()
            if part == "leader"
            else (
                sum((triangle.at(i) for i in range(triangle.size())), QPointF()) / triangle.size()
            ).toPoint()
        )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    assert tools.selected_id == datum.datum_id, (canvas.tool, point, canvas.rect(), canvas.message)
    assert QApplication.focusWidget() is canvas
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert not services.kernel.drawing_datum_identifiers
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


@pytest.mark.parametrize("crossing", [False, True])
@pytest.mark.parametrize("two_clicks", [False, True])
def test_datum_box_selection_and_delete(
    qtbot: QtBot, monkeypatch: MonkeyPatch, crossing: bool, two_clicks: bool
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    qtbot.waitExposed(window)
    qtbot.wait(100)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    tools.begin_datum()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 15)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, -15)))
    datum = services.kernel.drawing_datum_identifiers[0]
    first, second = ((5, 3), (-5, -3)) if crossing else ((-10, 22), (12, -22))
    start, end = canvas.local_to_screen(first), canvas.local_to_screen(second)
    if two_clicks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=end)
        assert tools.selected_ids == {datum.datum_id}, (
            canvas.message,
            tools.datum_screen_bounds(datum),
        )
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    else:
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tools.selected_ids == {datum.datum_id}, (
        canvas.message,
        canvas.tool,
        start,
        end,
        tools.datum_screen_bounds(datum),
        tools.datums,
    )
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert not services.kernel.drawing_datum_identifiers
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


def test_box_selects_referenced_datum_and_frame_together(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(uuid4().hex, "A", (0, 8), (0, -5))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (15, 8),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas.set_tool("选择元素")
    start, end = canvas.local_to_screen((-10, 20)), canvas.local_to_screen((50, -15))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tools.selected_ids == {datum.datum_id, frame.frame_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert not services.kernel.drawing_datum_identifiers
    assert not services.kernel.drawing_tolerance_frames
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_tolerance_frames == (frame,), timeout=10000)
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_datum_box_modifiers_and_cancel_preserve_selection(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    first = DatumIdentifier(uuid4().hex, "A", (-20, 5), (-20, -5))
    second = DatumIdentifier(uuid4().hex, "B", (20, 5), (20, -5))
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [first.to_mapping(), second.to_mapping()]},
        "local",
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(first).center().toPoint()
    )
    start, end = canvas.local_to_screen((15, 12)), canvas.local_to_screen((32, -12))
    for modifier, expected in (
        (Qt.KeyboardModifier.ControlModifier, {first.datum_id, second.datum_id}),
        (Qt.KeyboardModifier.ShiftModifier, {first.datum_id}),
    ):
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, modifier, start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, modifier, end)
        assert tools.selected_ids == expected
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tools.selected_ids == {first.datum_id}
    assert tools.selected_id == first.datum_id and tools.selected_kind == "datum"


def test_datum_box_skips_locked_and_ambiguous_identities(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    identity = uuid4().hex
    datum = DatumIdentifier(identity, "A", (0, 5), (0, -5))
    duplicate = FeatureControlFrame(identity, (ToleranceRow("flatness", 0.1, 2),), (15, 5))
    locked = DatumIdentifier(uuid4().hex, "B", (30, 5), (30, -5), layer_name="locked")
    canvas.set_layer_table(SketchLayerTable().add(SketchLayer("locked", locked=True)), "0")
    tools.sync((duplicate,), (datum, locked))
    first, second = (
        QPointF(canvas.local_to_screen((-10, 15))),
        QPointF(canvas.local_to_screen((50, -15))),
    )
    assert tools.select_box(first, second, Qt.KeyboardModifier.NoModifier)
    assert not tools.selected_ids and tools.selected_id is None


@pytest.mark.parametrize("clipboard", [False, True])
def test_datum_copy_name_dialog_has_room_for_window_title(qtbot: QtBot, clipboard: bool) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert (
        editor is not None
        and loaded is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    tools = editor.canvas.geometric_tolerance_tools
    datum = DatumIdentifier(uuid4().hex, "A", (0, 5), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    editor.canvas.set_tool("选择元素")
    assert _select_annotation(tools, datum.datum_id, "datum")
    sizes: list[int] = []

    def inspect_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        sizes.append(dialog.width())
        dialog.reject()

    if clipboard:
        assert editor.canvas.copy_to_clipboard()
        QTimer.singleShot(50, inspect_dialog)
        assert editor.canvas.begin_clipboard_paste()
    else:
        assert tools.handle_command("COPY")
        assert tools.handle_command("0,0")
        QTimer.singleShot(50, inspect_dialog)
        assert tools.handle_command("10,0")
    assert sizes and sizes[0] >= 320


def test_datum_name_dialog_has_room_for_window_title(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    sizes: list[int] = []

    def inspect_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        sizes.append(dialog.width())
        dialog.reject()

    QTimer.singleShot(50, inspect_dialog)
    editor.canvas.geometric_tolerance_tools.begin_datum()
    assert sizes and sizes[0] >= 320


@pytest.mark.parametrize("entry", ["toolbar", "AMDATUMID", "DATUMLABEL"])
def test_mechanical_datum_name_dialog_title_and_cancel(qtbot: QtBot, entry: str) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    if entry == "toolbar":
        window.act_datum_label.trigger()
    else:
        assert tools.handle_command(entry)
    assert tools.handle_command("0,0")
    captured: list[tuple[str, int, str]] = []

    def inspect_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        captured.append((dialog.windowTitle(), dialog.width(), dialog.textValue()))
        dialog.reject()

    QTimer.singleShot(50, inspect_dialog)
    assert tools.handle_command("10,10")
    assert len(captured) == 1
    assert captured[0][0] == "基准标识" and captured[0][2] == "A"
    assert captured[0][1] >= 320
    assert not tools.pending and not services.kernel.drawing_datum_identifiers


@pytest.mark.parametrize("kind", ["line", "spline"])
def test_datum_box_grip_keeps_normal_constraint_and_vertices(qtbot: QtBot, kind: str) -> None:
    import math
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_normal
    from mycad.core.sketch import LineEntity, Sketch, SplineEntity, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    entity = (
        LineEntity(uuid4().hex, (0, 0), (20, 0))
        if kind == "line"
        else SplineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(entity.entity_id, "geometry"),
        0.5,
        curve_kind="spline" if kind == "spline" else None,
        control_count=4 if kind == "spline" else None,
    )
    target, vertex = ((10, 0), (10, 3)) if kind == "line" else ((10, 5), (8, 7))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        target,
        attachment=attachment,
        leader_offsets=((-3, -4), (vertex[0] - 20, vertex[1] - 20)),
        leader_auto_normal=True,
        spline_normal_enabled=kind == "spline",
    )
    tools, canvas = editor.canvas.geometric_tolerance_tools, editor.canvas
    assert tools is not None and tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(datum.position_mm)
    )
    assert tools.handle_command("25,20")
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.position_mm == (25, 20)
    assert moved.leader_auto_normal and moved.spline_normal_enabled == (kind == "spline")
    assert (
        moved.position_mm[0] + moved.leader_offsets[-1][0],
        moved.position_mm[1] + moved.leader_offsets[-1][1],
    ) == pytest.approx(vertex)
    assert (
        moved.position_mm[0] + moved.leader_offsets[0][0],
        moved.position_mm[1] + moved.leader_offsets[0][1],
    ) == pytest.approx((17, 16))
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (moved,), timeout=10000)
    updated_entity = (
        replace(entity, end_mm=(20, 20))
        if isinstance(entity, LineEntity)
        else replace(entity, control_points_mm=((0, 0), (10, 0), (15, 10), (20, 10)))
    )
    updated_sketch = replace(sketch, entities=(updated_entity,))
    state = updated_sketch.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    updated = services.kernel.drawing_datum_identifiers[0]
    normal = resolve_attachment_normal(
        attachment, updated_sketch, updated.target_mm, enable_spline=True
    )
    assert normal is not None
    delta = (
        updated.position_mm[0] + updated.leader_offsets[-1][0] - updated.target_mm[0],
        updated.position_mm[1] + updated.leader_offsets[-1][1] - updated.target_mm[1],
    )
    assert math.hypot(*delta) == pytest.approx(math.dist(target, vertex))
    assert delta[0] * normal[1] - delta[1] * normal[0] == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize("action", ["MOVE", "COPY"])
def test_attached_normal_datum_move_and_copy_keep_vertex_side(
    qtbot: QtBot, monkeypatch: MonkeyPatch, action: str
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (10, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
        ),
        leader_offsets=((-3, -4), (-10, -17)),
        leader_auto_normal=True,
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        datum.datum_id,
        "datum",
        {datum.datum_id},
    )
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    assert tools.handle_command(action)
    assert tools.handle_command("0,0")
    assert tools.handle_command("0,-30")
    moved = services.kernel.drawing_datum_identifiers[-1]
    assert moved.position_mm == (20, -10)
    assert moved.target_mm == (10, 0) and moved.leader_auto_normal
    vertices = tuple(
        (moved.position_mm[0] + x, moved.position_mm[1] + y) for x, y in moved.leader_offsets
    )
    assert vertices[0] == pytest.approx((17, 16))
    assert vertices[1] == pytest.approx((10, 3))
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


def test_datum_box_and_target_grips_move_without_losing_annotation(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (25, 0))
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.position_mm == (5, 0) and moved.target_mm == (25, 0)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((25, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((30, 0)))
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (30, 0)


def test_attached_datum_target_grip_requires_valid_geometry(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    editor = window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (1, 2), (15, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 10),
        (1, 2),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 2)))
    assert tools.handle_command("50,50")
    assert tools.pending and services.kernel.drawing_datum_identifiers == (datum,)
    assert tools.handle_command("15,2")
    changed = services.kernel.drawing_datum_identifiers[0]
    assert changed.target_mm == (15, 2)
    assert changed.attachment is not None and changed.attachment.reference.kind == "end"


def test_datum_vertex_grip_edit_is_undoable(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (25, 0), leader_offsets=((10, -10),))
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    bounds = tools.datum_screen_bounds(datum)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=bounds.center().toPoint())
    assert tools.selected_id == datum.datum_id
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, -10)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, -10)))
    assert services.kernel.drawing_datum_identifiers[0].leader_offsets == ((15, -10),)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


@pytest.mark.parametrize("index", [0, 1])
def test_datum_normal_vertex_grip_releases_only_constrained_vertex(
    qtbot: QtBot, index: int
) -> None:
    import math
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (10, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
        ),
        leader_offsets=((-3, -4), (-10, -17)),
        leader_auto_normal=True,
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    tools.datum_grip = (datum, index)
    _place_annotation(tools, "datum", (18, 14) if index == 0 else (12, 3))
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.leader_auto_normal == (index == 0)
    if index == 0:
        changed = replace(sketch, entities=(replace(line, end_mm=(20, 20)),))
        state = changed.to_state_mapping()
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
        followed = services.kernel.drawing_datum_identifiers[0]
        vector = (
            followed.position_mm[0] + followed.leader_offsets[-1][0] - followed.target_mm[0],
            followed.position_mm[1] + followed.leader_offsets[-1][1] - followed.target_mm[1],
        )
        assert math.hypot(*vector) == pytest.approx(3)
        assert vector[0] + vector[1] == pytest.approx(0, abs=1e-9)
        loaded.bus.undo_operation()
        assert services.kernel.drawing_datum_identifiers == (updated,)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


def test_datum_vertex_grip_cancel_does_not_change_history(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (25, 0), leader_offsets=((10, -10),))
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, -10)))
    assert tools.cancel()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_datum_vertex_grip_accepts_coordinate(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (25, 0), leader_offsets=((10, -10),))
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, -10)))
    assert tools.handle_command("@5,0")
    assert services.kernel.drawing_datum_identifiers[0].leader_offsets == ((15, -10),)


def test_datum_bent_leader_is_selectable(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (25, 0), leader_offsets=((10, -10),))
    tools.sync((), (datum,))
    canvas.set_tool("选择元素")
    path, triangle = tools.datum_screen_path(datum)
    assert len(path) == 3 and triangle
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=((path[1] + path[2]) / 2).toPoint())
    assert tools.selected_id == datum.datum_id


def test_datum_screen_leader_leaves_label_box(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    for target in ((20, -20), (-20, -20), (-20, 20), (20, 20), (0, -20)):
        datum = DatumIdentifier(uuid4().hex, "A", (0, 0), target)
        rect = tools.datum_screen_bounds(datum)
        segment, triangle = tools.datum_screen_leader(datum, rect)
        assert segment is not None and triangle
        start, end = segment
        assert (
            min(
                abs(start.x() - rect.left()),
                abs(start.x() - rect.right()),
                abs(start.y() - rect.top()),
                abs(start.y() - rect.bottom()),
            )
            < 1e-6
        )
        assert not rect.adjusted(0.01, 0.01, -0.01, -0.01).contains((start + end) / 2)


def test_datum_box_scales_with_view_but_remains_pickable(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -10))
    tools.sync((), (datum,))
    canvas.set_tool("选择元素")
    before = tools.datum_screen_bounds(datum)
    canvas.zoom_view_factor(0.1)
    after = tools.datum_screen_bounds(datum)
    assert after.width() == pytest.approx(before.width() * 0.1)
    assert after.height() == pytest.approx(before.height() * 0.1)
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        pos=QPointF(after.right() + 3, after.center().y()).toPoint(),
    )
    assert tools.selected_id == datum.datum_id


def test_long_datum_label_fits_frame_and_is_selectable(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import DrawingText, TextStyle
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.ui.text_layout import layout_text

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(uuid4().hex, "LONG_DATUM_LABEL", (0, 0), (0, -5))
    tools.sync((), (datum,))
    canvas.set_tool("选择元素")
    label = layout_text(
        DrawingText("0" * 32, datum.label, (0, 0)), TextStyle(height_mm=3.5), tools.manager
    )
    bounds = tools.datum_screen_bounds(datum)
    assert bounds.width() >= label.bounds.width() * canvas.view_scale
    point = QPointF(bounds.right() - 2, bounds.center().y()).toPoint()
    assert point.x() > canvas.local_to_screen(datum.position_mm).x() + max(
        5 * canvas.view_scale, 15
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    assert tools.selected_id == datum.datum_id


def test_command_bar_creates_geometric_tolerance_and_datum(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from mycad.core.geometric_tolerance import DatumReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    bar = editor.drawing_command_bar.input
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    bar.setText("DATUMLABEL")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert tools.mechanical_datum_active
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, -10))
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    datum = services.kernel.drawing_datum_identifiers[0]

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.rows[0].characteristic.setCurrentIndex(
            dialog.rows[0].characteristic.findData("position")
        )
        dialog.rows[0].value.setValue(0.05)
        dialog.rows[0].datums[0].setText("A")
        dialog.accept()

    QTimer.singleShot(20, accept)
    bar.setText("TOLERANCE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert tools.pending_rows
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.rows[0].datums == (DatumReference("A", datum.datum_id),)
    unit = window.execution_unit
    assert unit is not None
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )


def test_tolerance_toolbar_creates_attached_annotations_and_replays(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    from uuid import uuid4

    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    window.act_datum_label.trigger()
    for point in ((5, 0), (5, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert len(services.kernel.drawing_datum_identifiers) == 1
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.attachment is not None and datum.attachment.reference.entity_id == line.entity_id

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.rows[0].characteristic.setCurrentIndex(
            dialog.rows[0].characteristic.findData("position")
        )
        dialog.rows[0].value.setValue(0.1)
        dialog.rows[0].datums[0].setText("A")
        dialog.accept()

    window.act_geometric_tolerance.trigger()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    QTimer.singleShot(20, accept)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((20, 15))
    )
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.leader_arrow_style == "closed_filled"
    assert (
        frame.leader_attachment is not None
        and frame.leader_attachment.reference.entity_id == line.entity_id
    )
    assert frame.rows[0].datums[0].datum_id == datum.datum_id
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and not services.kernel.drawing_tolerance_frames, timeout=10000
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.drawing_tolerance_frames == (frame,),
        timeout=10000,
    )
    path = tmp_path / "toolbar-annotations.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)
    assert reopened.kernel.drawing_tolerance_frames == (frame,)


def test_tolerance_toolbar_actions_cancel_without_history(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert (
        editor is not None
        and loaded is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    tools = editor.canvas.geometric_tolerance_tools
    actions = editor.dimension_toolbar.actions()
    assert window.act_geometric_tolerance in actions and window.act_datum_label in actions
    count = loaded.document.command_count
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    window.act_datum_label.trigger()
    assert tools.mechanical_datum_active
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert not tools.pending and loaded.document.command_count == count

    window.act_geometric_tolerance.trigger()
    assert tools.mechanical_frame_active
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert not tools.pending and loaded.document.command_count == count


def test_tolerance_menu_actions_only_enable_for_drawing_and_open_tools(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    assert not window.act_geometric_tolerance.isEnabled()
    assert not window.act_datum_label.isEnabled()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert window.act_geometric_tolerance.isEnabled() and window.act_datum_label.isEnabled()
    assert window.act_geometric_tolerance in window.menu_tools.actions()
    assert window.act_datum_label in window.menu_tools.actions()
    monkeypatch.setattr(QInputDialog, "getText", _label_a)
    window.act_datum_label.trigger()
    assert tools.mechanical_datum_active
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)

    window.act_geometric_tolerance.trigger()
    assert tools.mechanical_frame_active
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert not tools.pending
    window.act_view_3d.trigger()
    assert window.active_workspace == "model"
    assert not window.act_geometric_tolerance.isEnabled()
    assert not window.act_datum_label.isEnabled()


def test_selecting_frame_reports_unresolved_datum_reference(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A"),)),), (0, 0)
    )
    tools.sync((frame,), ())
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert tools.selected_id == frame.frame_id
    assert "A" in editor.status_label.text() and "未关联" in editor.status_label.text()


def test_frame_precision_repair_roundtrips_through_ui_history_and_dxf(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference
    from mycad.core.persistence import save_document
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf
    from mycad.ui.geometric_tolerance_layout import layout_frame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    loaded, editor, unit = (
        window.loaded_document(),
        window.active_sketch_dialog(),
        window.execution_unit,
    )
    assert loaded is not None and editor is not None and unit is not None
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    row = ToleranceRow("position", 0.001, 2, datums=(DatumReference("A", datum.datum_id),))
    frame = FeatureControlFrame(uuid4().hex, (row,), (10, 10))
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    before = layout_frame(frame, tools.manager).rows[0].cells[1].text
    assert (
        before is not None
        and cast("tuple[QTextLayout, ...]", vars(before)["_paragraphs"])[0].text() == "精度不足"
    )
    editor.canvas.set_tool("选择元素")

    def fix_precision() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        assert "精度不足" in dialog.rows[0].value_notice.text()
        dialog.rows[0].precision.setValue(3)
        assert "精度不足" not in dialog.rows[0].value_notice.text()
        dialog.accept()

    QTimer.singleShot(20, fix_precision)
    QTest.mouseDClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    corrected = services.kernel.drawing_tolerance_frames[0]
    assert corrected.rows[0].value == 0.001 and corrected.rows[0].precision == 3
    assert corrected.rows[0].datums == row.datums
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (corrected,)
        ),
        timeout=10000,
    )
    project = tmp_path / "corrected-frame.my2d"
    save_document(loaded.document, project)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, project)
    assert reopened.kernel.drawing_tolerance_frames == (corrected,)
    output = tmp_path / "corrected-frame.dxf"
    write_sketches_dxf((), output, tolerance_frames=(corrected,), datum_identifiers=(datum,))
    result = read_sketch_dxf(output)
    assert result.tolerance_frames == (corrected,)
    assert result.datum_identifiers == (datum,)


def test_cadcraft_edited_frame_can_relink_datums_and_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from mycad.core.persistence import save_document
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    source = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-frame-edited.dxf"
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    queue_import = cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])
    queue_import(window, source, unit_override="mm")
    qtbot.waitUntil(lambda: len(services.kernel.drawing_tolerance_frames) == 15, timeout=10000)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    frame = next(item for item in services.kernel.drawing_tolerance_frames if len(item.rows) == 2)
    datums = {item.label: item.datum_id for item in services.kernel.drawing_datum_identifiers}
    assert set(datums) == {"A", "B", "C"}
    assert frame.rows[0].value == 0.25
    assert all(ref.datum_id is None for row in frame.rows for ref in row.datums)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    assert any(item.frame_id == frame.frame_id for item in tools.frames)
    editor.canvas.set_tool("选择元素")

    def relink() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        for row_index, count in ((0, 3), (1, 1)):
            for index in range(count):
                dialog.rows[row_index].datum_link_buttons[index].click()
        dialog.accept()

    QTimer.singleShot(20, relink)
    QTest.mouseDClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    linked = next(
        item for item in services.kernel.drawing_tolerance_frames if item.frame_id == frame.frame_id
    )
    assert linked.rows[0].value == 0.25
    assert all(ref.datum_id == datums[ref.label] for row in linked.rows for ref in row.datums)
    loaded.bus.undo_operation()
    assert frame in services.kernel.drawing_tolerance_frames
    loaded.bus.redo_operation()
    assert linked in services.kernel.drawing_tolerance_frames
    path = tmp_path / "cadcraft-relinked.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert linked in reopened.kernel.drawing_tolerance_frames
    output = tmp_path / "cadcraft-relinked.dxf"
    prepare_dxf_output_preview(reopened.kernel).write(output)
    exported = read_sketch_dxf(output)
    roundtripped = next(
        item for item in exported.tolerance_frames if item.frame_id == linked.frame_id
    )
    assert roundtripped.rows == linked.rows
    assert roundtripped.position_mm == linked.position_mm
    assert roundtripped.text_style_id == linked.text_style_id
    assert roundtripped.text_style_id is not None and linked.text_style_id is not None
    assert exported.text_styles is not None
    actual_style = exported.text_styles.get(roundtripped.text_style_id)
    expected_style = reopened.kernel.drawing_text_styles.get(linked.text_style_id)
    assert (
        actual_style.font_family,
        actual_style.font_style,
        actual_style.font_file,
        actual_style.height_mm,
        actual_style.width_factor,
    ) == (
        expected_style.font_family,
        expected_style.font_style,
        expected_style.font_file,
        expected_style.height_mm,
        expected_style.width_factor,
    )
    assert {item.label: item.datum_id for item in exported.datum_identifiers} == datums
    assert not any("未关联" in warning for warning in exported.report.warnings)


def test_unresolved_frame_datum_can_relink_and_undo(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A"),)),), (10, 10)
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    editor.canvas.set_tool("选择元素")

    def cancel_relink() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.rows[0].datum_link_buttons[0].click()
        dialog.reject()

    before = loaded.document.command_count
    QTimer.singleShot(20, cancel_relink)
    QTest.mouseDClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert loaded.document.command_count == before
    assert services.kernel.drawing_tolerance_frames == (frame,)

    def relink() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        assert "未关联" in dialog.rows[0].datum_statuses[0].text()
        dialog.rows[0].datum_link_buttons[0].click()
        dialog.accept()

    QTimer.singleShot(20, relink)
    QTest.mouseDClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    assert services.kernel.drawing_tolerance_frames[0].rows[0].datums == (
        DatumReference("A", datum.datum_id),
    )
    unit = window.execution_unit
    assert unit is not None
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames == (frame,)
        ),
        timeout=10000,
    )
    assert cast(
        "Callable[..., tuple[str, ...]]", _private_member(tools, "_unresolved_datum_labels")
    )(frame) == ("A",)
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.drawing_tolerance_frames[0].rows[0].datums[0].datum_id
            == datum.datum_id
        ),
        timeout=10000,
    )
    path = tmp_path / "relinked.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames[0].rows[0].datums == (
        DatumReference("A", datum.datum_id),
    )


def test_frame_exact_input_visible_without_scrolling(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QScrollArea

    dialog = GeometricToleranceDialog()
    qtbot.addWidget(dialog)
    dialog.resize(1000, 620)
    dialog.show()
    qtbot.wait(50)
    scroll = dialog.findChild(QScrollArea)
    assert scroll is not None
    button = dialog.rows[0].exact_value_button
    top_left = button.mapTo(scroll.viewport(), button.rect().topLeft())
    bottom_right = button.mapTo(scroll.viewport(), button.rect().bottomRight())
    assert scroll.viewport().rect().contains(top_left)
    assert scroll.viewport().rect().contains(bottom_right)


def test_frame_preview_tracks_rotation_and_fits(qtbot: QtBot) -> None:
    dialog = GeometricToleranceDialog()
    qtbot.addWidget(dialog)
    dialog.preview.setFixedSize(300, 200)

    def painted_size() -> tuple[int, int]:
        image = dialog.preview.grab().toImage()
        background = image.pixelColor(0, 0)
        points = [
            (x, y)
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y) != background
        ]
        assert points
        return (
            max(x for x, _ in points) - min(x for x, _ in points),
            max(y for _, y in points) - min(y for _, y in points),
        )

    horizontal = painted_size()
    dialog.rotation.setValue(90)
    assert dialog.preview.frame.rotation_deg == 90
    vertical = painted_size()
    assert horizontal[0] > horizontal[1]
    assert vertical[1] > vertical[0]
    assert vertical[0] < 280 and vertical[1] < 180


def test_frame_rotation_exact_input_and_validation(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    from PySide6.QtWidgets import QDialog

    dialog = GeometricToleranceDialog(rotation_deg=12.3456789)
    qtbot.addWidget(dialog)
    assert "12.3456789" in dialog.rotation_notice.text()
    monkeypatch.setattr(QInputDialog, "getText", _text_response("bad"))
    cast("Callable[..., None]", _private_member(dialog, "_enter_exact_rotation"))()
    dialog.accept()
    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QInputDialog, "getText", _text_response("-12.34567891"))
    cast("Callable[..., None]", _private_member(dialog, "_enter_exact_rotation"))()
    dialog.accept()
    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    assert dialog.rotation.precise_value() == -12.34567891


def test_editing_frame_value_retains_high_precision_rotation(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2),), (10, 10), rotation_deg=12.3456789
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    editor.canvas.set_tool("选择元素")

    def edit_value() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.rows[0].value.setValue(0.2)
        dialog.accept()

    QTimer.singleShot(20, edit_value)
    QTest.mouseDClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    updated = services.kernel.drawing_tolerance_frames[0]
    assert updated.rows[0].value == 0.2
    assert updated.rotation_deg == frame.rotation_deg
    loaded.bus.undo_operation()
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    path = tmp_path / "precise-frame-rotation.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (updated,)


def test_editing_frame_rotation_retains_high_precision_tolerance(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from uuid import uuid4

    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 1e-10, 2),), (10, 10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    editor.canvas.set_tool("选择元素")

    def edit_rotation() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        assert "原始值" in dialog.rows[0].value_notice.text()
        dialog.rotation.setValue(30)
        dialog.accept()

    QTimer.singleShot(20, edit_rotation)
    QTest.mouseDClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    updated = services.kernel.drawing_tolerance_frames[0]
    assert updated.rotation_deg == 30 and updated.rows[0].value == 1e-10
    path = tmp_path / "precise-tolerance.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (updated,)


def test_exact_frame_tolerance_input_saves_and_reopens(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert (
        loaded is not None
        and editor is not None
        and editor.canvas.geometric_tolerance_tools is not None
    )
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (10, 10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    editor.canvas.set_tool("选择元素")
    monkeypatch.setattr(QInputDialog, "getText", _text_response("1e-12"))

    def edit() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.rows[0].exact_value_button.click()
        dialog.accept()

    QTimer.singleShot(20, edit)
    QTest.mouseDClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(frame).center().toPoint()
    )
    updated = services.kernel.drawing_tolerance_frames[0]
    assert updated.rows[0].value == 1e-12
    path = tmp_path / "exact-tolerance.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (updated,)


def test_export_filter_selects_graphic_tolerance_compatibility(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    import ezdxf.filemanagement as filemanagement
    from ezdxf.document import Drawing
    from PySide6.QtWidgets import QFileDialog

    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    frame = FeatureControlFrame("fa" * 16, (ToleranceRow("position", 0.1, 1),), (2, 3))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    target = tmp_path / "compatibility.dxf"
    choice = "DXF 图形兼容（标注不可结构化编辑） (*.dxf)"
    offered: list[str] = []

    def choose(_parent: object, _title: str, _directory: str, filters: str) -> tuple[str, str]:
        offered.append(filters)
        return str(target), choice

    def accept(dialog: DxfOutputPreviewDialog) -> int:
        assert "不可作为结构化公差编辑" in dialog.report_label.text()
        return int(dialog.DialogCode.Accepted)

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", accept)
    window.act_export.trigger()
    qtbot.waitUntil(target.exists, timeout=20000)
    assert choice in offered[0]
    readfile = cast("Callable[[Path], Drawing]", vars(filemanagement)["readfile"])
    document = readfile(target)
    assert not document.modelspace().query("TOLERANCE")
    assert document.modelspace().query("LINE")


@pytest.mark.parametrize("graphic", [False, True])
def test_export_legacy_frame_uses_canvas_anchor_without_changing_history(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch, graphic: bool
) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement
    from ezdxf.document import Drawing
    from ezdxf.entities.leader import Leader
    from PySide6.QtWidgets import QFileDialog

    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        rotation_deg=30,
        leader_target_mm=(0, 0),
        leader_offsets=((-10, -5),),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    frame_anchor = cast(
        "Callable[[FeatureControlFrame], tuple[float, float] | None]",
        _private_member(tools, "_frame_leader_anchor"),
    )
    anchor = frame_anchor(frame)
    assert anchor is not None
    revision = loaded.document.revision
    target = tmp_path / "legacy-frame.dxf"
    choice = "DXF 图形兼容（标注不可结构化编辑） (*.dxf)" if graphic else "DXF 草图 (*.dxf)"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", _save_response(str(target), choice))

    def accept(dialog: DxfOutputPreviewDialog) -> int:
        assert "字体" in dialog.report_label.text()
        return int(dialog.DialogCode.Accepted)

    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", accept)
    window.act_export.trigger()
    qtbot.waitUntil(target.exists, timeout=20000)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert loaded.document.revision == revision
    if graphic:
        readfile = cast("Callable[[Path], Drawing]", vars(filemanagement)["readfile"])
        leader = cast("Leader", next(iter(readfile(target).modelspace().query("LEADER"))))
        assert tuple(leader.vertices[-1])[:2] == pytest.approx(anchor)
        assert tuple(leader.vertices[0])[:2] == pytest.approx(frame.leader_target_mm)
    else:
        result = read_sketch_dxf(target)
        imported = result.tolerance_frames[0]
        assert imported.leader_anchor_offset == pytest.approx(
            (anchor[0] - frame.position_mm[0], anchor[1] - frame.position_mm[1])
        )
        assert imported.leader_target_mm == frame.leader_target_mm
        assert imported.leader_offsets == frame.leader_offsets


def test_legacy_frame_export_reports_specific_font_substitution_and_missing_glyph(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from PySide6.QtWidgets import QFileDialog

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(tools.manager, "missing_glyphs", _missing_glyph)
    missing = TextStyle("missing", "图纸字体", font_family="MyCAD-Definitely-Not-Installed")
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), missing)).to_mapping(), "local"
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20, 20),
        text_style_id="missing",
        leader_target_mm=(0, 0),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    target = tmp_path / "font-substitution.dxf"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", _save_response(str(target), "DXF 草图 (*.dxf)")
    )
    messages: list[str] = []

    def reject(dialog: DxfOutputPreviewDialog) -> int:
        messages.append(dialog.report_label.text())
        return int(dialog.DialogCode.Rejected)

    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", reject)
    window.act_export.trigger()
    qtbot.waitUntil(lambda: bool(messages), timeout=20000)
    assert "MyCAD-Definitely-Not-Installed" in messages[0]
    assert "缺少字符：字" in messages[0]
    assert not target.exists()
    assert services.kernel.drawing_tolerance_frames == (frame,)


@pytest.mark.parametrize("graphic", [False, True])
def test_legacy_frame_export_omits_vertices_hidden_inside_frame(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch, graphic: bool
) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement
    from ezdxf.document import Drawing
    from ezdxf.entities.leader import Leader
    from PySide6.QtWidgets import QFileDialog

    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((1, -3), (-10, -5)),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    screen_path = tools.frame_screen_leader(frame)
    assert len(screen_path) == 3
    target = tmp_path / "visible-leader.dxf"
    choice = "DXF 图形兼容（标注不可结构化编辑） (*.dxf)" if graphic else "DXF 草图 (*.dxf)"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", _save_response(str(target), choice))

    def accept(dialog: DxfOutputPreviewDialog) -> int:
        assert "顶点未写入可见路径" in dialog.report_label.text()
        return int(dialog.DialogCode.Accepted)

    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", accept)
    window.act_export.trigger()
    qtbot.waitUntil(target.exists, timeout=20000)
    if graphic:
        readfile = cast("Callable[[Path], Drawing]", vars(filemanagement)["readfile"])
        leader = cast("Leader", next(iter(readfile(target).modelspace().query("LEADER"))))
        assert len(leader.vertices) == 3
        assert tuple(leader.vertices[1])[:2] == pytest.approx((10, 15))
    else:
        imported = read_sketch_dxf(target).tolerance_frames[0]
        assert imported.leader_offsets == ((-10, -5),)
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_graphic_tolerance_export_cancel_preserves_existing_file(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QFileDialog

    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    frame = FeatureControlFrame("fb" * 16, (ToleranceRow("flatness", 0.1, 1),), (2, 3))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    target = tmp_path / "existing.dxf"
    target.write_bytes(b"original")
    choice = "DXF 图形兼容（标注不可结构化编辑） (*.dxf)"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", _save_response(str(target), choice))
    shown: list[str] = []

    def reject(dialog: DxfOutputPreviewDialog) -> int:
        shown.append(dialog.report_label.text())
        return int(dialog.DialogCode.Rejected)

    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", reject)
    window.act_export.trigger()
    qtbot.waitUntil(lambda: bool(shown), timeout=20000)
    assert "不可作为结构化公差编辑" in shown[0]
    assert target.read_bytes() == b"original"
    assert "取消" in window.status_command.text()


@pytest.mark.parametrize("with_tangency", [False, True])
def test_drawing_revision_entry_preserves_cyclic_polyline_constraint(
    qtbot: QtBot, with_tangency: bool
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import CircleEntity, PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    constraint = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(polyline.entity_id, "segment", 0),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,), (constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation: CrossSketchTangency | None = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 2), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, polyline.entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    current = services.kernel.sketches[0]
    attachment = DatumAttachment(
        current.sketch_id, SketchGeometryReference(polyline.entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 5), (2.5, 0), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    rotated = replace(polyline, points_mm=(*polyline.points_mm[1:], polyline.points_mm[0]))
    updated_constraint = replace(
        constraint, references=(SketchGeometryReference(polyline.entity_id, "segment", 3),)
    )
    state = replace(
        current, entities=(rotated,), constraints=(updated_constraint,)
    ).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 57
    assert services.kernel.sketches[0].constraints == (updated_constraint,)
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx((2.5, 0))
    if relation is not None:
        expected = replace(relation, first=replace(relation.first, segment_index=3))
        assert services.kernel.cross_sketch_tangencies == (expected,)


@pytest.mark.parametrize(
    ("rotated", "base_index", "replacement", "extra", "extra_uses_source", "edit_extra_source"),
    [
        (False, None, False, False, False, False),
        (True, None, False, False, False, False),
        (True, 0, False, False, False, False),
        (True, 1, False, False, False, False),
        (True, None, True, False, False, False),
        (True, 1, True, False, False, False),
        (True, 1, True, True, False, False),
        (True, 1, True, True, True, False),
        (True, 1, True, True, False, True),
    ],
)
def test_drawing_revision_maps_array_source_when_only_member_has_annotation(
    qtbot: QtBot,
    rotated: bool,
    base_index: int | None,
    replacement: bool,
    extra: bool,
    extra_uses_source: bool,
    edit_extra_source: bool,
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = (
        PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
        if rotated
        else PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    )
    if rotated:
        turned = rotate_entities((source,), (source.entity_id,), (0, 0), 90)[0]
        translated = move_entities((turned,), (source.entity_id,), (0, 20))[0]
        assert isinstance(translated, PolylineEntity)
        target = replace(translated, entity_id=uuid4().hex)
    else:
        target = PolylineEntity(uuid4().hex, ((0, 20), (10, 20), (10, 30)))
    source_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    target_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    for item in (source_sketch, target_sketch):
        app.commit_new_sketch(services, loaded, item, session_identity=0)
    source_ref = ArrayEntityRef(source_sketch.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(target_sketch.sketch_id, target.entity_id)
    replacement_data: ArrayReplacement | None = None
    if replacement:
        replacement_entity = replace(
            source,
            entity_id=uuid4().hex,
            points_mm=tuple((x + 30, y) for x, y in source.points_mm),
        )
        replacement_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (replacement_entity,))
        app.commit_new_sketch(services, loaded, replacement_sketch, session_identity=0)
        replacement_data = ArrayReplacement(
            ArrayEntityRef(replacement_sketch.sketch_id, replacement_entity.entity_id)
        )
    extra_outputs: tuple[ArrayExtraOutput, ...] = ()
    annotation_sketch, annotation_entity = target_sketch, target
    extra_source, extra_source_sketch = source, source_sketch
    if extra:
        extra_source = replace(source, entity_id=uuid4().hex)
        extra_target = replace(target, entity_id=uuid4().hex)
        extra_source_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (extra_source,))
        annotation_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (extra_target,))
        annotation_entity = extra_target
        for item in (extra_source_sketch, annotation_sketch):
            app.commit_new_sketch(services, loaded, item, session_identity=0)
        extra_outputs = (
            ArrayExtraOutput(
                source_ref
                if extra_uses_source
                else ArrayEntityRef(extra_source_sketch.sketch_id, extra_source.entity_id),
                ArrayEntityRef(annotation_sketch.sketch_id, extra_target.entity_id),
                source_ref,
                1,
                0,
                rotation_deg=90 if rotated else 0,
            ),
        )
    array = AssociativeRectArray(
        uuid4().hex,
        source_sketch.frame,
        2,
        1,
        20,
        0,
        (source_ref,),
        (
            ArrayMember(
                source_ref,
                target_ref,
                1,
                0,
                rotation_deg=90 if rotated else 0,
                replacement=replacement_data,
            ),
        ),
        base_point=(
            ArrayBasePoint(
                source=source_ref,
                reference=SketchGeometryReference(source.entity_id, "vertex", base_index),
            )
            if base_index is not None
            else None
        ),
        extra_outputs=extra_outputs,
    )
    loaded.bus.execute(
        "drawing.array.add", {"array": array.to_mapping()}, "local", version=14 if extra else None
    )
    attachment = DatumAttachment(
        annotation_sketch.sketch_id,
        SketchGeometryReference(annotation_entity.entity_id, "segment", 0),
        0.25,
        4 if rotated else 2,
    )
    point = resolve_attachment_local(attachment, {annotation_entity.entity_id: annotation_entity})
    assert point is not None
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 26),
        leader_target_mm=point,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local", version=10
    )
    edited = extra_source if edit_extra_source else source
    edited_sketch = extra_source_sketch if edit_extra_source else source_sketch
    current = next(
        item for item in services.kernel.sketches if item.sketch_id == edited_sketch.sketch_id
    )
    reverse = replace(
        edited,
        points_mm=(edited.points_mm[0], *reversed(edited.points_mm[1:]))
        if rotated
        else tuple(reversed(edited.points_mm)),
    )
    state = replace(current, entities=(reverse,)).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == (
        62
        if edit_extra_source
        else 61
        if extra_uses_source
        else 60
        if extra
        else 59
        if replacement
        else 58
        if base_index == 1
        else 57
    )
    updated = services.kernel.drawing_tolerance_frames[0]
    assert updated.leader_attachment is not None
    assert updated.leader_attachment.reference.index == (
        3
        if extra_uses_source or edit_extra_source
        else 0
        if replacement or extra
        else 3
        if rotated
        else 1
    )
    assert updated.leader_target_mm == pytest.approx(point)
    if base_index == 1 and not edit_extra_source:
        updated_array = services.kernel.associative_arrays[0]
        assert (
            updated_array.base_point is not None and updated_array.base_point.reference is not None
        )
        assert updated_array.base_point.reference.index == 3
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.associative_arrays == (array,)


def test_cadcraft_leader_import_box_select_delete_undo_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from mycad.core.persistence import save_document

    source = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-leader-moved.dxf"
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor, unit = (
        window.loaded_document(),
        window.active_sketch_dialog(),
        window.execution_unit,
    )
    assert loaded is not None and editor is not None and unit is not None
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    queue_import = cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])
    queue_import(window, source, unit_override="mm")
    qtbot.waitUntil(lambda: len(services.kernel.drawing_tolerance_frames) == 1, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.leader_target_mm == pytest.approx((1, 0))
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_tool("选择元素")
    start, end = canvas.local_to_screen((13, 11)), canvas.local_to_screen((9, 7))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tools.selected_ids == {frame.frame_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert not services.kernel.drawing_tolerance_frames
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_tolerance_frames == (frame,), timeout=10000)
    path = tmp_path / "cadcraft-leader.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (frame,)


def test_cadcraft_independent_leader_import_undo_redo_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity

    source = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-frame-independent-leader.dxf"
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    reports: list[str] = []

    def confirm(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        reports.append(str(args[2]))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    queue_import = cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])
    queue_import(window, source, unit_override="mm")
    qtbot.waitUntil(lambda: len(services.kernel.drawing_tolerance_frames) == 1, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert any("引线" in report and "普通图元" in report for report in reports)
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.leader_target_mm is None
    sketches = services.kernel.sketches
    assert any(
        isinstance(entity, LineEntity)
        and entity.start_mm == pytest.approx((0, 0))
        and entity.end_mm == pytest.approx((20, 18))
        for sketch in sketches
        for entity in sketch.entities
    )
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not services.kernel.drawing_tolerance_frames and not services.kernel.sketches
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.sketches == sketches
    path = tmp_path / "cadcraft-independent-leader.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (frame,)
    assert reopened.kernel.sketches == sketches


@pytest.mark.parametrize("selection", ["click", "crossing"])
def test_cadcraft_short_leader_is_selectable_after_import(
    qtbot: QtBot, monkeypatch: MonkeyPatch, selection: str
) -> None:
    source = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-short-leader-resaved.dxf"
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    queue_import = cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])
    queue_import(window, source, unit_override="mm")
    qtbot.waitUntil(lambda: len(services.kernel.drawing_tolerance_frames) == 1, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    frame = services.kernel.drawing_tolerance_frames[0]
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_tool("选择元素")
    if selection == "click":
        points = tools.frame_screen_leader(frame)
        assert len(points) == 2
        QTest.mouseClick(
            canvas, Qt.MouseButton.LeftButton, pos=((points[0] + points[1]) / 2).toPoint()
        )
    else:
        start, end = canvas.local_to_screen((0.8, 3)), canvas.local_to_screen((-3, -3))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tools.selected_ids == {frame.frame_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert not services.kernel.drawing_tolerance_frames
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_tolerance_frames == (frame,), timeout=10000)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_leader_vertex_grip_mouse_retries_after_overlap(qtbot: QtBot, owner: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    assert tools.execute is not None
    if owner == "frame":
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (0, 0),
            leader_target_mm=(25, 0),
            leader_offsets=((10, -10),),
            leader_anchor_offset=(2, -2),
        )
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [item.to_mapping()]})
        box = tools.screen_bounds(item)
        identity = item.frame_id
    else:
        item = DatumIdentifier(uuid4().hex, "A", (0, 0), (25, 0), leader_offsets=((10, -10),))
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [item.to_mapping()]})
        box = tools.datum_screen_bounds(item)
        identity = item.datum_id
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=box.center().toPoint())
    assert tools.selected_id == identity
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, -10)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((25, 0)))
    assert "重合" in canvas.message
    assert (tools.frame_grip if owner == "frame" else tools.datum_grip) is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, -10)))
    updated = (
        services.kernel.drawing_tolerance_frames[0]
        if owner == "frame"
        else services.kernel.drawing_datum_identifiers[0]
    )
    assert updated.leader_offsets == ((15, -10),)
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            services.kernel.drawing_tolerance_frames == (item,)
            if owner == "frame"
            else services.kernel.drawing_datum_identifiers == (item,)
        ),
        timeout=10000,
    )


@pytest.mark.parametrize("hidden_owner", ["frame", "text"])
def test_mixed_frame_text_paste_rejects_hidden_target_layer(
    qtbot: QtBot, hidden_owner: str
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    tools, text_tools = editor.canvas.geometric_tolerance_tools, editor.canvas.text_tools
    assert tools is not None and tools.execute is not None and text_tools is not None
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 5),
        layer_name="GDT" if hidden_owner == "frame" else "0",
    )
    note = DrawingText(
        uuid4().hex, "note", (0, 0), layer_name="GDT" if hidden_owner == "text" else "0"
    )
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    assert tools.execute(
        "drawing.text.batch", {"add": [note.to_mapping()], "update": [], "remove": []}
    )
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    text_tools.selected_ids = {note.text_id}
    assert editor.canvas.copy_to_clipboard()
    hidden = layers.replace(replace(layers.get("GDT"), visible=False))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": hidden.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    assert editor.canvas.begin_clipboard_paste()
    count = loaded.document.command_count
    _place_annotation(tools, "mixed", (15, 8))
    assert loaded.document.command_count == count
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_texts == (note,)
    assert "隐藏" in editor.canvas.message


def test_toolbar_mechanical_frame_mouse_vertex_and_undo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    window.act_geometric_tolerance.trigger()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    bar = editor.drawing_command_bar.input
    bar.setFocus()
    QTest.keyClicks(bar, "V")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8, 8)))

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, 15)))
    assert len(services.kernel.drawing_tolerance_frames) == 1
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.leader_target_mm == pytest.approx((5, 0), abs=0.2)
    assert frame.position_mm == pytest.approx((15, 15), abs=0.2)
    assert frame.leader_offsets[0] == pytest.approx((-7, -7), abs=0.4)
    assert frame.leader_attachment is not None
    assert frame.leader_attachment.reference.entity_id == line.entity_id
    window.request_undo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_tolerance_frames, timeout=10000)


@pytest.mark.parametrize("hidden_owner", ["geometry", "dimension"])
def test_mixed_geometry_frame_paste_rejects_hidden_target_layer(
    qtbot: QtBot, hidden_owner: str
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(
        uuid4().hex, (0, 0), (20, 0), layer_name="GDT" if hidden_owner == "geometry" else "0"
    )
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, -10),
        layer_name="GDT" if hidden_owner == "dimension" else None,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint,), layers=layers)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (20, 10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        tools.screen_bounds(frame).center().toPoint(),
    )
    assert line.entity_id in editor.canvas.selected_entity_ids
    assert editor.canvas.copy_to_clipboard()
    hidden = layers.replace(replace(layers.get("GDT"), visible=False))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": hidden.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    assert editor.canvas.begin_clipboard_paste()
    count = loaded.document.command_count
    original_sketches = services.kernel.sketches
    _place_annotation(tools, "mixed", (40, 10))
    assert loaded.document.command_count == count
    assert services.kernel.sketches == original_sketches
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert "隐藏" in editor.canvas.message


@pytest.mark.parametrize("kind", ["datum", "frame"])
@pytest.mark.parametrize("stage", ["vertex", "position"])
def test_toolbar_annotation_escape_after_mouse_and_command_input(
    qtbot: QtBot, kind: str, stage: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    count = loaded.document.command_count
    (window.act_datum_label if kind == "datum" else window.act_geometric_tolerance).trigger()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    bar = editor.drawing_command_bar.input
    bar.setFocus()
    QTest.keyClicks(bar, "V")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    if stage == "position":
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 5)))
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
    else:
        QTest.keyClick(bar, Qt.Key.Key_Escape)
    assert not tools.pending
    assert loaded.document.command_count == count
    assert not services.kernel.drawing_datum_identifiers
    assert not services.kernel.drawing_tolerance_frames


@pytest.mark.parametrize("kind", ["angular_3p", "angular_2l"])
def test_reflex_reference_arc_is_drawn_and_pickable(qtbot: QtBot, kind: str) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.detached_dimension_layout import layout_reference_dimension
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    dimension = DetachedDimension(
        uuid4().hex, kind, (0, 10), (10, 0), (-10, 0), 0, 270, vertex_mm=(0, 0)
    )
    layout = layout_reference_dimension(dimension, canvas)
    assert "270.00°" in layout.text.main
    assert layout.hit(QPointF(canvas.local_to_screen((0, -10))))
    assert not layout.hit(QPointF(canvas.local_to_screen((7.07, 7.07))))


@pytest.mark.parametrize("side", [1, -1])
def test_straight_reference_arc_is_drawn_on_selected_side(qtbot: QtBot, side: int) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.detached_dimension_layout import layout_reference_dimension
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    dimension = DetachedDimension(
        uuid4().hex,
        "angular_3p",
        (side * 10, 0),
        (-side * 10, 0),
        (0, side * 15),
        0,
        180,
        vertex_mm=(0, 0),
    )
    layout = layout_reference_dimension(dimension, canvas)
    assert "180.00°" in layout.text.main
    assert layout.hit(QPointF(canvas.local_to_screen((10.61, side * 10.61))))
    assert not layout.hit(QPointF(canvas.local_to_screen((10.61, -side * 10.61))))


def test_imported_straight_angle_can_be_selected_moved_and_undone(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.dimension_tolerance import DimensionTolerance

    source = DetachedDimension(
        uuid4().hex,
        "angular_3p",
        (-10, 0),
        (10, 0),
        (0, -15),
        0,
        180,
        DimensionTolerance("deviation", 0.1, -0.2),
        vertex_mm=(0, 0),
    )
    path = tmp_path / "straight-lower.dxf"
    write_sketches_dxf((), path, reference_dimensions=(source,))
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", errors.append)
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(lambda: len(services.kernel.drawing_reference_dimensions) == 1, timeout=10000)
    assert not errors
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    qtbot.waitUntil(lambda: len(tools.reference_dimensions) == 1, timeout=10000)
    imported = tools.reference_dimensions[0]
    assert imported.first_mm == (-10, 0) and imported.tolerance == source.tolerance
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=editor.canvas.local_to_screen((10.61, -10.61)),
    )
    assert tools.selected_id == imported.dimension_id
    assert tools.handle_command("MOVE")
    assert tools.handle_command("0,0")
    assert tools.handle_command("3,4")
    moved = services.kernel.drawing_reference_dimensions[0]
    assert moved.first_mm == (-7, 4) and moved.location_mm == (3, -11)
    window.request_undo()
    qtbot.waitUntil(
        lambda: services.kernel.drawing_reference_dimensions == (imported,), timeout=10000
    )


def test_drawing_revision_entry_rejects_three_cycle_retarget(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10), (30, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(polyline.entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    state = replace(
        sketch,
        entities=(replace(polyline, points_mm=((13, 4), (13, 14), (3, 4), (25, 17), (36, 18))),),
    ).to_state_mapping()
    revisions = [
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    count = loaded.document.command_count
    submit = cast("Callable[..., None]", vars(type(window))["_submit_drawing_revisions"])
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("target", ["dimension", "geometry", "geometry_and_owner"])
@pytest.mark.parametrize("owner", ["frame", "datum"])
def test_delete_dimension_attached_to_unselected_tolerance_is_explained(
    qtbot: QtBot, tmp_path: Path, owner: str, target: str
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import AnnotationAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, -10),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    attachment = AnnotationAttachment(
        "sketch_dimension", dimension.constraint_id, (0, 0), sketch.sketch_id
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    if owner == "frame":
        frame = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 5),
            leader_target_mm=(10, -10),
            leader_annotation_attachment=attachment,
        )
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
        identity = frame.frame_id
    else:
        datum = DatumIdentifier(
            uuid4().hex, "A", (10, 5), (10, -10), annotation_attachment=attachment
        )
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
        identity = datum.datum_id
    count = loaded.document.command_count
    if target == "geometry_and_owner":
        tools.selected_id, tools.selected_kind, tools.selected_ids = identity, owner, {identity}
    if target == "dimension":
        editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    else:
        editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    if target == "geometry_and_owner":
        unit = window.execution_unit
        assert unit is not None
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert not services.kernel.drawing_tolerance_frames, editor.status_label.text()
        assert not services.kernel.drawing_datum_identifiers, editor.status_label.text()
        assert not services.kernel.sketches[0].entities, editor.status_label.text()
        assert not services.kernel.sketches[0].constraints
        window.request_undo()
        qtbot.waitUntil(
            lambda: (
                not unit.is_busy
                and not unit.is_delivering_result
                and services.kernel.sketches == (sketch,)
            ),
            timeout=10000,
        )
        assert len(services.kernel.drawing_tolerance_frames) == int(owner == "frame")
        assert len(services.kernel.drawing_datum_identifiers) == int(owner == "datum")
        window.request_redo()
        qtbot.waitUntil(
            lambda: (
                not unit.is_busy
                and not unit.is_delivering_result
                and not services.kernel.sketches[0].entities
            ),
            timeout=10000,
        )
        assert not services.kernel.sketches[0].constraints
        assert not services.kernel.drawing_tolerance_frames
        assert not services.kernel.drawing_datum_identifiers
        from mycad.core.persistence import save_document

        path = tmp_path / "deleted-geometry-and-tolerance.my2d"
        save_document(loaded.document, path)
        reopened = app.build_app(discoverers=())
        app.open_app_document(reopened, path)
        assert not reopened.kernel.sketches[0].entities
        assert not reopened.kernel.sketches[0].constraints
        assert not reopened.kernel.drawing_tolerance_frames
        assert not reopened.kernel.drawing_datum_identifiers
        return
    assert "尺寸仍被标注附着" in editor.status_label.text()
    assert "请先解除附着" in editor.status_label.text()
    assert "ReplayFailure" not in editor.status_label.text()
    assert services.kernel.sketches == (sketch,)
    assert loaded.document.command_count == count


@pytest.mark.parametrize("owner", ["frame", "datum"])
def test_delete_geometry_and_frame_attached_by_unselected_annotation_is_explained(
    qtbot: QtBot, tmp_path: Path, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import AnnotationAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    target = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [target.to_mapping()]})
    ref = AnnotationAttachment("frame", target.frame_id, (0, 0))
    if owner == "frame":
        dependent = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (20, 5),
            leader_target_mm=(10, 5),
            leader_annotation_attachment=ref,
        )
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [dependent.to_mapping()]})
        dependent_id = dependent.frame_id
    else:
        datum = DatumIdentifier(uuid4().hex, "A", (20, 5), (10, 5), annotation_attachment=ref)
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
        dependent_id = datum.datum_id
    count = loaded.document.command_count
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        target.frame_id,
        "frame",
        {target.frame_id},
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert "公差框仍被标注附着" in editor.status_label.text()
    assert "ReplayFailure" not in editor.status_label.text()
    assert services.kernel.sketches == (sketch,)
    assert loaded.document.command_count == count
    tools.selected_ids = {target.frame_id, dependent_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_tolerance_frames
            and not services.kernel.drawing_datum_identifiers
        ),
        timeout=10000,
    )
    assert not services.kernel.sketches[0].entities
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches == (sketch,), timeout=10000
    )
    assert len(services.kernel.drawing_tolerance_frames) == (2 if owner == "frame" else 1)
    assert len(services.kernel.drawing_datum_identifiers) == int(owner == "datum")
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.sketches[0].entities
        ),
        timeout=10000,
    )
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_datum_identifiers
    from mycad.core.persistence import save_document

    path = tmp_path / "deleted-attached-frame.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert not reopened.kernel.sketches[0].entities
    assert not reopened.kernel.drawing_tolerance_frames
    assert not reopened.kernel.drawing_datum_identifiers


@pytest.mark.parametrize("owner", ["frame", "datum"])
def test_delete_geometry_and_referenced_dimension_reports_attached_annotation(
    qtbot: QtBot, tmp_path: Path, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import AnnotationAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    dim = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    assert tools.execute("drawing.reference_dimensions.batch", {"add": [dim.to_mapping()]})
    attachment = AnnotationAttachment("reference_dimension", dim.dimension_id, (0, 0))
    if owner == "frame":
        frame = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 5),
            leader_target_mm=(0, 5),
            leader_annotation_attachment=attachment,
        )
        assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
        dependent_id = frame.frame_id
    else:
        datum = DatumIdentifier(uuid4().hex, "A", (10, 5), (0, 5), annotation_attachment=attachment)
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
        dependent_id = datum.datum_id
    count = loaded.document.command_count
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        dim.dimension_id,
        "reference",
        {dim.dimension_id},
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert "参考尺寸仍被标注附着" in editor.status_label.text()
    assert "ReplayFailure" not in editor.status_label.text()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_reference_dimensions == (dim,)
    assert loaded.document.command_count == count
    tools.selected_ids = {dim.dimension_id, dependent_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_reference_dimensions
        ),
        timeout=10000,
    )
    assert not services.kernel.sketches[0].entities
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_datum_identifiers
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches == (sketch,), timeout=10000
    )
    assert services.kernel.drawing_reference_dimensions == (dim,)
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_reference_dimensions
        ),
        timeout=10000,
    )
    assert not services.kernel.sketches[0].entities
    from mycad.core.persistence import save_document

    path = tmp_path / "deleted-attached-reference.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert not reopened.kernel.sketches[0].entities
    assert not reopened.kernel.drawing_reference_dimensions
    assert not reopened.kernel.drawing_tolerance_frames
    assert not reopened.kernel.drawing_datum_identifiers


def test_sync_restores_remaining_tolerance_selection_after_primary_deleted(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    datum = DatumIdentifier(uuid4().hex, "A", (20, 5), (20, 0))
    assert tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    assert _select_annotation(tools, frame.frame_id, "frame")
    assert _select_annotation(tools, datum.datum_id, "datum", additive=True)
    assert tools.selected_id == datum.datum_id
    assert tools.execute("drawing.tolerance.batch", {"remove_datums": [datum.datum_id]})
    assert tools.selected_ids == {frame.frame_id}
    assert tools.selected_id == frame.frame_id
    assert tools.selected_kind == "frame"
    assert editor.canvas.delete_selected()
    assert not services.kernel.drawing_tolerance_frames
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_tolerance_frames == (frame,), timeout=10000)


@pytest.mark.parametrize("kind", ["datum", "reference"])
def test_sync_restores_kind_for_remaining_annotation(qtbot: QtBot, kind: str) -> None:
    from uuid import uuid4

    from mycad.core.detached_dimension import DetachedDimension

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    if kind == "datum":
        datum = DatumIdentifier(uuid4().hex, "A", (20, 5), (20, 0))
        assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
        identity = datum.datum_id
    else:
        dimension = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
        assert tools.execute(
            "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}
        )
        identity = dimension.dimension_id
    assert _select_annotation(tools, identity, kind)
    assert _select_annotation(tools, frame.frame_id, "frame", additive=True)
    assert tools.execute("drawing.tolerance.batch", {"remove_frames": [frame.frame_id]})
    assert tools.selected_ids == {identity}
    assert tools.selected_id == identity
    assert tools.selected_kind == kind
    assert editor.canvas.delete_selected()
    assert not services.kernel.drawing_datum_identifiers
    assert not services.kernel.drawing_reference_dimensions


def test_tolerance_sync_drops_ambiguous_selection_and_keeps_unique_objects(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    identity = uuid4().hex
    first = FeatureControlFrame(identity, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    second = DatumIdentifier(uuid4().hex, "B", (20, 5), (20, 0))
    tools.sync((first,), (second,))
    assert _select_annotation(tools, second.datum_id, "datum")
    assert _select_annotation(tools, first.frame_id, "frame", additive=True)
    duplicate = DatumIdentifier(identity, "A", (0, 5), (0, 0))
    tools.sync((first,), (second, duplicate))
    assert tools.selected_ids == {second.datum_id}
    assert tools.selected_id == second.datum_id
    assert tools.selected_kind == "datum"
    assert "身份重复" in editor.status_label.text()


def test_tolerance_sync_deselects_identity_reused_for_different_kind(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    identity = uuid4().hex
    frame = FeatureControlFrame(identity, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    tools.sync((frame,), ())
    assert _select_annotation(tools, identity, "frame")
    replacement = DatumIdentifier(identity, "A", (20, 5), (20, 0))
    tools.sync((), (replacement,))
    assert not tools.selected_ids
    assert tools.selected_id is None
    assert "标注类型已改变" in editor.status_label.text()


def test_unresolved_datum_case_change_requires_explicit_relink(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumReference

    datum = DatumIdentifier(uuid4().hex, "A", (10, 5), (10, 0))
    row = ToleranceRow("position", 0.1, 2, datums=(DatumReference("A"),))
    dialog = GeometricToleranceDialog(rows=(row,), available=(datum,))
    qtbot.addWidget(dialog)
    field = dialog.rows[0].datums[0]
    assert dialog.rows[0].datum_statuses[0].text() == "未关联"
    field.setText("a")
    assert dialog.rows[0].datum_statuses[0].text() == "未关联"
    assert dialog.values()[0].datums[0].datum_id is None
    assert dialog.rows[0].datum_link_buttons[0].isEnabled()
    dialog.rows[0].datum_link_buttons[0].click()
    assert dialog.values()[0].datums[0].datum_id == datum.datum_id


def test_linked_datum_case_change_preserves_identity_and_new_label_can_link(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumReference

    first = DatumIdentifier(uuid4().hex, "A", (10, 5), (10, 0))
    second = DatumIdentifier(uuid4().hex, "B", (20, 5), (20, 0))
    row = ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", first.datum_id),))
    dialog = GeometricToleranceDialog(rows=(row,), available=(first, second))
    qtbot.addWidget(dialog)
    field = dialog.rows[0].datums[0]
    field.setText("a")
    assert dialog.rows[0].datum_statuses[0].text() == "已关联"
    assert dialog.values()[0].datums[0] == DatumReference("A", first.datum_id)
    assert dialog.preview.frame.rows[0].datums[0] == DatumReference("A", first.datum_id)
    field.setText("B")
    assert dialog.values()[0].datums[0].datum_id == second.datum_id


def test_unresolved_datum_case_edit_roundtrips_without_implicit_relink(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumReference
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (10, 5), (10, 0))
    row = ToleranceRow("position", 0.1, 2, datums=(DatumReference("A"),))
    frame = FeatureControlFrame(uuid4().hex, (row,), (20, 5))
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    dialog = GeometricToleranceDialog(rows=frame.rows, available=(datum,))
    qtbot.addWidget(dialog)
    dialog.rows[0].datums[0].setText("a")
    updated = FeatureControlFrame(frame.frame_id, dialog.values(), frame.position_mm)
    loaded.bus.execute(
        "drawing.tolerance.batch", {"update_frames": [updated.to_mapping()]}, "local"
    )
    assert services.kernel.drawing_tolerance_frames[0].rows[0].datums == (DatumReference("a"),)
    loaded.bus.undo()
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo()
    path = tmp_path / "unresolved-case.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames[0].rows[0].datums == (DatumReference("a"),)


def test_linked_datum_preview_matches_committed_and_reopened_label(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumReference
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (10, 5), (10, 0))
    row = ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),))
    frame = FeatureControlFrame(uuid4().hex, (row,), (20, 5))
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    dialog = GeometricToleranceDialog(rows=frame.rows, available=(datum,))
    qtbot.addWidget(dialog)
    dialog.rows[0].datums[0].setText("a")
    preview_rows = dialog.preview.frame.rows
    assert preview_rows[0].datums == (DatumReference("A", datum.datum_id),)
    updated = FeatureControlFrame(frame.frame_id, dialog.values(), frame.position_mm)
    loaded.bus.execute(
        "drawing.tolerance.batch", {"update_frames": [updated.to_mapping()]}, "local"
    )
    assert services.kernel.drawing_tolerance_frames[0].rows == preview_rows
    path = tmp_path / "canonical-datum-label.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames[0].rows == preview_rows


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("override", [False, True])
def test_mechanical_attached_first_vertex_defaults_to_normal_with_shift_f_override(
    qtbot: QtBot, owner: str, override: bool
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 20))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_orthogonal_enabled(False)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    assert tools.handle_command("V")
    if override:
        window.activateWindow()
        canvas.setFocus()
        qtbot.waitUntil(canvas.hasFocus, timeout=10000)
        QTest.keyClick(canvas, Qt.Key.Key_F, Qt.KeyboardModifier.ShiftModifier)
        assert not tools.mechanical_leader_orthogonal, editor.status_label.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((4, 8)))
    vertices = (
        tools.mechanical_datum_vertices if owner == "datum" else tools.mechanical_frame_vertices
    )
    assert vertices[0] == pytest.approx((4, 8) if override else (-2, 2), abs=0.2)


def test_mechanical_shift_f_toggles_from_command_input(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.begin_mechanical_datum()
    command = editor.drawing_command_bar.input
    window.activateWindow()
    command.setFocus()
    qtbot.waitUntil(command.hasFocus, timeout=10000)
    QTest.keyClick(command, Qt.Key.Key_F, Qt.KeyboardModifier.ShiftModifier)
    assert not tools.mechanical_leader_orthogonal
    assert command.text() == ""
    QTest.keyClick(command, Qt.Key.Key_F, Qt.KeyboardModifier.ShiftModifier)
    assert tools.mechanical_leader_orthogonal
    assert command.text() == ""
    assert tools.cancel()
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_F, Qt.KeyboardModifier.ShiftModifier)
    assert command.text().lower() == "f"
    tools.begin_mechanical_datum()
    assert tools.mechanical_leader_orthogonal


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_default_normal_vertex_persists_undo_redo_and_reopen(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 20))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_orthogonal_enabled(False)
    monkeypatch.setattr(QInputDialog, "getText", _label_a)

    def accept_dialog(_dialog: GeometricToleranceDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept_dialog)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    assert tools.handle_command("V")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((4, 8)))
    assert tools.handle_command("10,10")
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert len(items) == 1 and items[0].leader_auto_normal
    expected = items[0]
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_datum_identifiers
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and bool(
                services.kernel.drawing_datum_identifiers
                or services.kernel.drawing_tolerance_frames
            )
        ),
        timeout=10000,
    )
    path = tmp_path / "default-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    reopened_items = (
        reopened.kernel.drawing_datum_identifiers
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames
    )
    assert reopened_items == (expected,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_direct_box_placement_keeps_default_normal_leader(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (20, 20)),))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_orthogonal_enabled(False)
    monkeypatch.setattr(QInputDialog, "getText", _label_a)

    def accept_dialog(_dialog: GeometricToleranceDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept_dialog)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    QTest.mouseMove(canvas, canvas.local_to_screen((10, 15)))
    preview = tools.mechanical_datum_preview if owner == "datum" else None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 15)))
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert len(items) == 1 and items[0].leader_auto_normal
    item = items[0]
    if owner == "datum":
        assert preview is not None and preview.route_algorithm_version == 4
        assert preview.box_size_mm is not None
    assert item.leader_offsets
    vertex = (
        item.position_mm[0] + item.leader_offsets[-1][0],
        item.position_mm[1] + item.leader_offsets[-1][1],
    )
    assert vertex[0] + vertex[1] == pytest.approx(0, abs=1e-8)
    if isinstance(item, DatumIdentifier):
        path, _ = tools.datum_screen_path(item)
    else:
        path = tools.frame_screen_leader(item)
    assert len(path) >= 2
    segment = path[-2] - path[-1]
    assert segment.x() == pytest.approx(segment.y(), abs=1e-6)
    assert len(path) == 3
    second = path[0] - path[1]
    assert abs(second.x()) < 1e-6 or abs(second.y()) < 1e-6


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_direct_normal_remains_visible_when_box_crosses_normal(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (20, 0)),))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_orthogonal_enabled(False)
    monkeypatch.setattr(QInputDialog, "getText", _label_a)

    def accept_dialog(_dialog: GeometricToleranceDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept_dialog)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-1, 10)))
    if owner == "datum":
        item = services.kernel.drawing_datum_identifiers[0]
        path, _ = tools.datum_screen_path(item)
    else:
        item = services.kernel.drawing_tolerance_frames[0]
        path = tools.frame_screen_leader(item)
    assert item.leader_auto_normal
    assert len(path) >= 2
    segment = path[-2] - path[-1]
    assert segment.x() == pytest.approx(0, abs=1e-6)
    for start, end in zip(path[:-2], path[1:-1], strict=True):
        assert abs(start.x() - end.x()) < 1e-6 or abs(start.y() - end.y()) < 1e-6
    dxf_path = tmp_path / "direct-normal.dxf"
    write_sketches_dxf(
        (sketch,),
        dxf_path,
        datum_identifiers=(item,) if isinstance(item, DatumIdentifier) else (),
        tolerance_frames=(item,) if isinstance(item, FeatureControlFrame) else (),
    )
    imported = read_sketch_dxf(dxf_path)
    restored = imported.datum_identifiers if owner == "datum" else imported.tolerance_frames
    assert restored == (item,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_direct_box_shift_f_override_keeps_free_leader(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (20, 20)),))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_orthogonal_enabled(False)
    monkeypatch.setattr(QInputDialog, "getText", _label_a)

    def accept_dialog(_dialog: GeometricToleranceDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept_dialog)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    window.activateWindow()
    canvas.setFocus()
    qtbot.waitUntil(canvas.hasFocus, timeout=10000)
    QTest.keyClick(canvas, Qt.Key.Key_F, Qt.KeyboardModifier.ShiftModifier)
    assert not tools.mechanical_leader_orthogonal
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 15)))
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert len(items) == 1
    assert not items[0].leader_auto_normal and not items[0].leader_offsets


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_direct_surface_leader_defaults_to_normal(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    editor.canvas.set_orthogonal_enabled(False)
    monkeypatch.setattr(QInputDialog, "getText", _label_a)

    def accept_dialog(_dialog: GeometricToleranceDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept_dialog)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("5,0")
    assert tools.handle_command("F")
    assert tools.handle_command("8,8")
    assert tools.handle_command("20,20")
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert len(items) == 1
    indication = items[0].surface_indication
    assert indication is not None and indication.auto_normal and indication.auto_route
    assert indication.leader_offsets_mm[-1][0] == pytest.approx(0, abs=1e-8)
    from mycad.core.persistence import save_document

    path = tmp_path / "surface-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    reopened_items = (
        reopened.kernel.drawing_datum_identifiers
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames
    )
    assert reopened_items == items
    dxf_path = tmp_path / "surface-normal.dxf"
    write_sketches_dxf(
        (sketch,),
        dxf_path,
        datum_identifiers=(items[0],) if isinstance(items[0], DatumIdentifier) else (),
        tolerance_frames=(items[0],) if isinstance(items[0], FeatureControlFrame) else (),
    )
    imported = read_sketch_dxf(dxf_path)
    imported_items = imported.datum_identifiers if owner == "datum" else imported.tolerance_frames
    assert imported_items[0].surface_indication == indication


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_leader_subsequent_vertex_defaults_to_axis_constraint(
    qtbot: QtBot, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (20, 20)),))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_orthogonal_enabled(False)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    assert tools.handle_command("V")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((4, 8)))
    assert tools.handle_command("V")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 7)))
    vertices = (
        tools.mechanical_datum_vertices if owner == "datum" else tools.mechanical_frame_vertices
    )
    assert len(vertices) == 2
    assert vertices[0] == pytest.approx((-2, 2), abs=0.2)
    assert vertices[1] == pytest.approx((5, 2), abs=0.2)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_direct_box_origin_on_tangent_uses_box_center(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (20, 20)),))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    editor.canvas.set_orthogonal_enabled(False)
    monkeypatch.setattr(QInputDialog, "getText", _label_a)

    def accept_dialog(_dialog: GeometricToleranceDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept_dialog)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    assert tools.handle_command("10,10")
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert len(items) == 1 and items[0].leader_auto_normal


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_surface_rejects_reference_on_tangent_without_guessing(
    qtbot: QtBot, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (20, 0)),))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("5,0")
    assert tools.handle_command("F")
    assert tools.handle_command("10,0")
    assert tools.surface_joint is None
    assert "Shift+F" in editor.status_label.text()


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_direct_box_attached_to_circle_uses_radial_normal(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 10),))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    editor.canvas.set_orthogonal_enabled(False)
    monkeypatch.setattr(QInputDialog, "getText", _label_a)

    def accept_dialog(_dialog: GeometricToleranceDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept_dialog)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("10,0")
    assert tools.handle_command("25,10")
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert len(items) == 1 and items[0].leader_auto_normal
    item = items[0]
    normal_vertex = (
        item.position_mm[0] + item.leader_offsets[-1][0],
        item.position_mm[1] + item.leader_offsets[-1][1],
    )
    assert normal_vertex[1] == pytest.approx(0, abs=1e-8)
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not services.kernel.drawing_datum_identifiers
            and not services.kernel.drawing_tolerance_frames
        ),
        timeout=10000,
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and bool(
                services.kernel.drawing_datum_identifiers
                or services.kernel.drawing_tolerance_frames
            )
        ),
        timeout=10000,
    )
    path = tmp_path / "circle-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    reopened_items = (
        reopened.kernel.drawing_datum_identifiers
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames
    )
    assert reopened_items == (item,)


def test_mechanical_frame_direct_preview_shows_normal_when_origin_on_tangent(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (20, 20)),))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    QTest.mouseMove(editor.canvas, editor.canvas.local_to_screen((10, 10)))
    qtbot.waitUntil(lambda: tools.mechanical_frame_cursor is not None, timeout=10000)
    vertices = tools.mechanical_frame_preview_vertices
    assert vertices
    assert vertices[0][0] + vertices[0][1] == pytest.approx(0, abs=1e-8)


def test_mechanical_shift_f_does_not_disable_global_f8(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (20, 20)),))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_orthogonal_enabled(True)
    tools.begin_mechanical_datum()
    assert tools.handle_command("0,0")
    assert tools.handle_command("V")
    window.activateWindow()
    canvas.setFocus()
    qtbot.waitUntil(canvas.hasFocus, timeout=10000)
    QTest.keyClick(canvas, Qt.Key.Key_F, Qt.KeyboardModifier.ShiftModifier)
    assert not tools.mechanical_leader_orthogonal and canvas.orthogonal_enabled
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((4, 8)))
    assert tools.mechanical_datum_vertices[0] == pytest.approx((-2, 2), abs=0.2)


@pytest.mark.parametrize("angle", [0, 45, 90])
def test_rotated_frame_direct_normal_has_axis_aligned_following_segments(
    qtbot: QtBot, monkeypatch: MonkeyPatch, angle: int
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (20, 0)),))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None

    def accept_dialog(dialog: GeometricToleranceDialog) -> int:
        dialog.rotation.setValue(angle)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept_dialog)
    tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    assert tools.handle_command("-1,10")
    frame = services.kernel.drawing_tolerance_frames[0]
    path = tools.frame_screen_leader(frame)
    assert frame.leader_auto_normal and len(path) >= 2
    assert (path[-2] - path[-1]).x() == pytest.approx(0, abs=1e-6)
    for start, end in zip(path[:-2], path[1:-1], strict=True):
        assert abs(start.x() - end.x()) < 1e-6 or abs(start.y() - end.y()) < 1e-6


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_shift_f_refreshes_mechanical_pointer_preview_without_mouse_move(
    qtbot: QtBot, owner: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (20, 20)),))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_orthogonal_enabled(False)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    assert tools.handle_command("V")
    window.activateWindow()
    canvas.setFocus()
    qtbot.waitUntil(canvas.hasFocus, timeout=10000)
    canvas.pointer_moved.emit(canvas.local_to_screen((4, 8)))

    def cursor() -> tuple[float, float] | None:
        return tools.mechanical_datum_cursor if owner == "datum" else tools.mechanical_frame_cursor

    qtbot.waitUntil(lambda: cursor() == pytest.approx((-2, 2), abs=0.2), timeout=10000)
    QTest.keyClick(canvas, Qt.Key.Key_F, Qt.KeyboardModifier.ShiftModifier)
    assert not tools.mechanical_leader_orthogonal
    assert cursor() == pytest.approx((4, 8), abs=0.2)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_automatically_routed_leader_stays_orthogonal_when_target_rotates(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path, owner: str
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)

    def accept_dialog(_dialog: GeometricToleranceDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept_dialog)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("0,0")
    assert tools.handle_command("10,10")
    updated = replace(sketch, entities=(replace(line, end_mm=(0, 20)),)).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": updated["entities"],
                    "constraints": updated["constraints"],
                }
            ]
        },
        "local",
    )
    sync(window)
    if owner == "datum":
        item = services.kernel.drawing_datum_identifiers[0]
        path, _ = tools.datum_screen_path(item)
    else:
        item = services.kernel.drawing_tolerance_frames[0]
        path = tools.frame_screen_leader(item)
    assert item.leader_auto_normal and len(path) >= 2
    assert (path[-2] - path[-1]).y() == pytest.approx(0, abs=1e-6)
    assert all((point - path[-1]).manhattanLength() > 1e-6 for point in path[:-1])
    for start, end in zip(path[:-2], path[1:-1], strict=True):
        assert abs(start.x() - end.x()) < 1e-6 or abs(start.y() - end.y()) < 1e-6
    assert item.leader_auto_route
    loaded.bus.undo()
    prior = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert prior.leader_auto_route and prior != item
    loaded.bus.redo()
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == item
    from mycad.core.persistence import save_document

    path_file = tmp_path / "rerouted-normal.my2d"
    save_document(loaded.document, path_file)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path_file)
    reopened_items = (
        reopened.kernel.drawing_datum_identifiers
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames
    )
    assert reopened_items == (item,)
    dxf = tmp_path / "rerouted-normal.dxf"
    write_sketches_dxf(
        services.kernel.sketches,
        dxf,
        datum_identifiers=(item,) if isinstance(item, DatumIdentifier) else (),
        tolerance_frames=(item,) if isinstance(item, FeatureControlFrame) else (),
    )
    imported = read_sketch_dxf(dxf)
    imported_items = imported.datum_identifiers if owner == "datum" else imported.tolerance_frames
    assert imported_items == (item,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("grip", [-2, 0])
def test_manual_leader_grip_disables_automatic_route(owner: str, grip: int) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "start"))
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (10, 10),
            (0, 0),
            attachment=attachment,
            leader_offsets=((-10, -5),),
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
            route_track_target=True,
            route_algorithm_version=2,
        )
        name = "_datum_with_grip"
        operation = cast(
            "Callable[[DatumIdentifier, int, tuple[float, float]], DatumIdentifier]",
            getattr(GeometricToleranceTools, name),
        )
        changed = operation(item, grip, (4, 7))
    else:
        frame = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 10),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            leader_offsets=((-10, -5),),
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
            route_track_target=True,
            route_algorithm_version=2,
        )
        changed = _frame_grip_value(frame, grip, (4, 7))
    assert not changed.leader_auto_route
    assert not changed.route_avoid_crossing and not changed.route_track_target
    assert changed.route_algorithm_version == 1


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_automatic_surface_leader_stays_orthogonal_when_target_rotates(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path, owner: str
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance_geometry import surface_indication_geometry
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)

    def accept_dialog(_dialog: GeometricToleranceDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept_dialog)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("5,0")
    assert tools.handle_command("F")
    assert tools.handle_command("8,8")
    assert tools.handle_command("20,20")
    state = replace(
        sketch, entities=(replace(line, start_mm=(5, -5), end_mm=(5, 15)),)
    ).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    item = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert item.surface_indication is not None
    assert item.surface_indication.auto_normal and item.surface_indication.auto_route
    target = item.target_mm if isinstance(item, DatumIdentifier) else item.leader_target_mm
    assert target is not None
    _, leader, _ = surface_indication_geometry(target, item.surface_indication)
    assert leader[-2][1] == pytest.approx(leader[-1][1], abs=1e-8)
    for start, end in zip(leader[:-2], leader[1:-1], strict=True):
        assert abs(start[0] - end[0]) < 1e-8 or abs(start[1] - end[1]) < 1e-8

    loaded.bus.undo()
    prior = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert prior != item and prior.surface_indication is not None
    assert prior.surface_indication.auto_route
    loaded.bus.redo()
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == item
    from mycad.core.persistence import save_document

    path = tmp_path / "surface-rerouted.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    reopened_items = (
        reopened.kernel.drawing_datum_identifiers
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames
    )
    assert reopened_items == (item,)
    dxf = tmp_path / "surface-rerouted.dxf"
    write_sketches_dxf(
        services.kernel.sketches,
        dxf,
        datum_identifiers=(item,) if isinstance(item, DatumIdentifier) else (),
        tolerance_frames=(item,) if isinstance(item, FeatureControlFrame) else (),
    )
    imported = read_sketch_dxf(dxf)
    imported_items = imported.datum_identifiers if owner == "datum" else imported.tolerance_frames
    assert imported_items[0].surface_indication == item.surface_indication


@pytest.mark.parametrize("grip", [-3, -4, -5, -6, -7])
def test_surface_automatic_route_is_released_after_grip_edit(grip: int) -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication
    from mycad.ui.geometric_tolerance_tools import GeometricToleranceTools

    surface = SurfaceIndication(
        (5, 8),
        (10, 8),
        0.5,
        ((0, 3), (5, 3)),
        auto_normal=True,
        auto_route=True,
        route_avoid_crossing=True,
    )
    edit_grip = cast(
        "Callable[[tuple[float, float], SurfaceIndication, int, tuple[float, float]], SurfaceIndication]",
        vars(GeometricToleranceTools)["_surface_with_grip"],
    )
    changed = edit_grip((0, 0), surface, grip, (3, 4))
    assert not changed.auto_route and not changed.route_avoid_crossing
    assert changed.auto_normal == (grip != -6)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_moving_automatic_leader_box_preserves_route(owner: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "start"))
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (10, 5),
            (0, 0),
            attachment=attachment,
            leader_offsets=((-10, 0),),
            leader_auto_normal=True,
            leader_auto_route=True,
        )
        operation = cast(
            "Callable[[DatumIdentifier, int, tuple[float, float]], DatumIdentifier]",
            vars(GeometricToleranceTools)["_datum_with_grip"],
        )
        changed = operation(item, -1, (14, 8))
    else:
        frame = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 5),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            leader_offsets=((-10, 0),),
            leader_auto_normal=True,
            leader_auto_route=True,
        )
        changed = _frame_grip_value(frame, -1, (14, 8))
    assert changed.leader_auto_route and changed.leader_auto_normal
    vertices = [
        (changed.position_mm[0] + x, changed.position_mm[1] + y) for x, y in changed.leader_offsets
    ]
    assert vertices[-1] == pytest.approx((0, 5))
    points = [changed.position_mm, *vertices]
    for first, second in zip(points[:-1], points[1:], strict=True):
        assert first[0] == pytest.approx(second[0]) or first[1] == pytest.approx(second[1])


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("action", ["MOVE", "COPY", "paste"])
def test_auto_routed_annotation_move_copy_keeps_route(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path, owner: str, action: str
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 5),
        (10, 0),
        attachment=attachment,
        leader_offsets=((-10, 0),),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=2,
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20, 5),
        leader_target_mm=(10, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        leader_offsets=((-10, 0),),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=2,
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    params: dict[str, object] = (
        {"add_datums": [datum.to_mapping()]}
        if owner == "datum"
        else {"add_frames": [frame.to_mapping()]}
    )
    assert tools.execute("drawing.tolerance.batch", params)
    identity = datum.datum_id if owner == "datum" else frame.frame_id
    tools.selected_id, tools.selected_kind, tools.selected_ids = identity, owner, {identity}
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    if action == "paste":
        assert tools.copy_frame_to_clipboard()
        assert tools.begin_frame_paste()
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((24, 8))
        )
    else:
        assert tools.handle_command(action)
        assert tools.handle_command("0,0")
        assert tools.handle_command("4,3")
    item = (
        services.kernel.drawing_datum_identifiers[-1]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[-1]
    )
    assert item.position_mm == pytest.approx((24, 8), abs=0.1)
    assert item.leader_auto_route and item.leader_auto_normal
    vertices = [(item.position_mm[0] + x, item.position_mm[1] + y) for x, y in item.leader_offsets]
    assert vertices[-1] == pytest.approx((10, 5))
    for start, end in zip(vertices[:-1], vertices[1:], strict=True):
        assert abs(start[0] - end[0]) < 1e-8 or abs(start[1] - end[1]) < 1e-8

    state = replace(
        sketch, entities=(replace(line, start_mm=(10, -10), end_mm=(10, 10)),)
    ).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    updated = (
        services.kernel.drawing_datum_identifiers[-1]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[-1]
    )
    assert updated.leader_auto_route
    vertices = [
        (updated.position_mm[0] + x, updated.position_mm[1] + y) for x, y in updated.leader_offsets
    ]
    assert vertices[-1][1] == pytest.approx(0, abs=1e-8)
    for start, end in zip(vertices[:-1], vertices[1:], strict=True):
        assert abs(start[0] - end[0]) < 1e-8 or abs(start[1] - end[1]) < 1e-8
    loaded.bus.undo()
    assert (
        services.kernel.drawing_datum_identifiers[-1]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[-1]
    ) == item
    loaded.bus.redo()
    assert (
        services.kernel.drawing_datum_identifiers[-1]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[-1]
    ) == updated

    if action == "MOVE":
        from mycad.core.persistence import save_document

        path = tmp_path / "moved-auto-leader.my2d"
        save_document(loaded.document, path)
        reopened = app.build_app(discoverers=())
        app.open_app_document(reopened, path)
        restored = (
            reopened.kernel.drawing_datum_identifiers[-1]
            if owner == "datum"
            else reopened.kernel.drawing_tolerance_frames[-1]
        )
        assert restored == updated
        dxf = tmp_path / "moved-auto-leader.dxf"
        write_sketches_dxf(
            reopened.kernel.sketches,
            dxf,
            datum_identifiers=(updated,) if isinstance(updated, DatumIdentifier) else (),
            tolerance_frames=(updated,) if isinstance(updated, FeatureControlFrame) else (),
        )
        imported = read_sketch_dxf(dxf)
        imported_items = (
            imported.datum_identifiers if owner == "datum" else imported.tolerance_frames
        )
        assert imported_items == (updated,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_moving_box_across_arrow_reroutes_without_overlap(owner: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "start"))
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (10, 5),
            (0, 0),
            attachment=attachment,
            leader_offsets=((-10, 0),),
            leader_auto_normal=True,
            leader_auto_route=True,
        )
        operation = cast(
            "Callable[[DatumIdentifier, int, tuple[float, float]], DatumIdentifier]",
            vars(GeometricToleranceTools)["_datum_with_grip"],
        )
        changed = operation(item, -1, (10, 3))
    else:
        frame = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 5),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            leader_offsets=((-10, 0),),
            leader_auto_normal=True,
            leader_auto_route=True,
        )
        changed = _frame_grip_value(frame, -1, (10, 3))
    assert changed.leader_auto_route
    vertices = [
        (changed.position_mm[0] + x, changed.position_mm[1] + y) for x, y in changed.leader_offsets
    ]
    assert vertices[-1] == pytest.approx((0, 5))
    assert all(not (abs(x) < 1e-8 and -1e-8 <= y < 5 - 1e-8) for x, y in vertices)
    points = [changed.position_mm, *vertices]
    for first, second in zip(points[:-1], points[1:], strict=True):
        assert first[0] == pytest.approx(second[0]) or first[1] == pytest.approx(second[1])


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mechanical_auto_leader_follows_rotating_arc(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path, owner: str
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 180)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)

    def accept_dialog(_dialog: GeometricToleranceDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept_dialog)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("10,0")
    assert tools.handle_command("25,10")
    before = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert before.leader_auto_route and before.route_avoid_crossing
    state = replace(sketch, entities=(replace(arc, start_angle_deg=90),)).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=56,
    )
    updated = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    target = updated.target_mm if isinstance(updated, DatumIdentifier) else updated.leader_target_mm
    assert target is not None
    assert target == pytest.approx((0, 10), abs=1e-8)
    normal = (
        updated.position_mm[0] + updated.leader_offsets[-1][0],
        updated.position_mm[1] + updated.leader_offsets[-1][1],
    )
    assert normal[0] == pytest.approx(target[0], abs=1e-8)
    assert updated.leader_auto_route and updated.route_avoid_crossing
    loaded.bus.undo_operation()
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == before
    loaded.bus.redo_operation()
    path = tmp_path / "arc-route.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert (
        reopened.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames[0]
    ) == updated


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mixed_move_auto_leader_transient_overlap_from_canvas(qtbot: QtBot, owner: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (20, 5),
            (10, 0),
            attachment=attachment,
            leader_offsets=((-10, 0),),
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
            route_track_target=True,
            route_algorithm_version=2,
        )
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (20, 5),
            leader_target_mm=(10, 0),
            leader_attachment=attachment,
            leader_offsets=((-10, 0),),
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
            route_track_target=True,
            route_algorithm_version=2,
        )
        params = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas, tools = editor.canvas, editor.canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    bounds = (
        tools.datum_screen_bounds(item)
        if isinstance(item, DatumIdentifier)
        else tools.screen_bounds(item)
    )
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        bounds.center().toPoint(),
    )
    assert tools.handle_command("MOVE")
    assert tools.handle_command("0,0")
    assert tools.handle_command("0,5")
    moved = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert moved.position_mm == pytest.approx((20, 10))
    assert moved.leader_auto_route and moved.route_track_target
    moved_line = services.kernel.sketches[0].entities[0]
    assert isinstance(moved_line, LineEntity)
    assert moved_line.start_mm == pytest.approx((0, 5))
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.sketches == (sketch,), timeout=10000)
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == item


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_crossing_selects_and_deletes_rerouted_automatic_leader(
    qtbot: QtBot, monkeypatch: MonkeyPatch, owner: str
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    qtbot.waitExposed(window)
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    canvas, tools = editor.canvas, editor.canvas.geometric_tolerance_tools
    assert tools is not None
    monkeypatch.setattr(QInputDialog, "getText", _label_a)

    def accept_dialog(_dialog: GeometricToleranceDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept_dialog)
    if owner == "datum":
        tools.begin_mechanical_datum()
    else:
        tools.begin_mechanical_frame()
    assert tools.handle_command("0,0") and tools.handle_command("30,20")
    state = replace(sketch, entities=(replace(line, end_mm=(0, 20)),)).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=56,
    )
    sync(window)
    item = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert item.leader_auto_route
    assert item.route_algorithm_version == (4 if owner == "datum" else 2)
    if isinstance(item, DatumIdentifier):
        assert item.box_size_mm is not None
        points, _ = tools.datum_screen_path(item)
        identity = item.datum_id
    else:
        points = tools.frame_screen_leader(item)
        identity = item.frame_id
    segments = [
        (a, b)
        for a, b in zip(points[:-2], points[1:-1], strict=True)
        if (b - a).manhattanLength() > 30
    ]
    assert segments
    a, b = max(segments, key=lambda part: (part[1] - part[0]).manhattanLength())
    point = (a + b) / 2
    canvas.set_tool("选择元素")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=(point + QPointF(9, -9)).toPoint())
    QTest.mouseMove(canvas, (point + QPointF(-9, 9)).toPoint())
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=(point + QPointF(-9, 9)).toPoint())
    assert tools.selected_ids == {identity}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert not (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    unit = window.execution_unit
    assert unit is not None
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and bool(
                services.kernel.drawing_datum_identifiers
                if owner == "datum"
                else services.kernel.drawing_tolerance_frames
            )
        ),
        timeout=10000,
    )
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == item
    sync(window)
    bounds = (
        tools.datum_screen_bounds(item)
        if isinstance(item, DatumIdentifier)
        else tools.screen_bounds(item)
    )
    xs = [bounds.left(), bounds.right(), *(point.x() for point in points)]
    ys = [bounds.top(), bounds.bottom(), *(point.y() for point in points)]
    start = QPointF(min(xs) - 18, min(ys) - 18).toPoint()
    end = QPointF(max(xs) + 18, max(ys) + 18).toPoint()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert identity in tools.selected_ids, (
        start,
        end,
        canvas.rect(),
        canvas.message,
        canvas.tool,
        tools.datums,
        tools.frames,
        tools.datum_screen_path(item) if isinstance(item, DatumIdentifier) else (),
        canvas.selected_entity_ids,
    )


def test_datum_recorded_box_size_controls_canvas_bounds(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(
        uuid4().hex, "A", (2, 3), (30, 0), layout_mode="shared", box_size_mm=(8, 5)
    )
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    bounds = tools.datum_screen_bounds(datum)
    assert bounds.width() == pytest.approx(8 * editor.canvas.view_scale)
    assert bounds.height() == pytest.approx(5 * editor.canvas.view_scale)


@pytest.mark.parametrize("algorithm", [3, 4])
@pytest.mark.parametrize("action", ["MOVE", "COPY", "paste"])
def test_box_aware_datum_single_move_copy_uses_recorded_box(
    qtbot: QtBot, monkeypatch: MonkeyPatch, action: str, algorithm: int
) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle
    from mycad.core.geometric_tolerance_geometry import datum_leader_path, reroute_leader_around_box
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.formats.dxf_datum import datum_box_dimensions

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (13, 7), (18, -4))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (-4, -3),
        (13, 7),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=reroute_leader_around_box(
            (-4, -3),
            ((10, 15), (6, 5)),
            (2, 2),
            (13, 7),
            (-4, -3, 1.212759544541193, -8),
            orthogonal_box_side=algorithm == 4,
        ),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=algorithm,
        layout_mode="shared",
        box_size_mm=(5.212759544541193, 5),
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        datum.datum_id,
        "datum",
        {datum.datum_id},
    )
    monkeypatch.setattr(QInputDialog, "getText", _label_b)
    if action == "paste":
        assert tools.copy_frame_to_clipboard()
        assert tools.begin_frame_paste()
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
        )
    else:
        assert tools.handle_command(action)
        assert tools.handle_command("0,0") and tools.handle_command("4,3")
    moved = services.kernel.drawing_datum_identifiers[-1]
    assert moved.position_mm == pytest.approx((0, 0))
    expected_size = (
        datum.box_size_mm if action == "MOVE" else datum_box_dimensions("B", TextStyle())
    )
    assert moved.route_algorithm_version == algorithm and moved.box_size_mm == pytest.approx(
        expected_size
    )
    assert moved.box_size_mm is not None
    path = datum_leader_path(
        (0, 0, moved.box_size_mm[0], -moved.box_size_mm[1]),
        moved.target_mm,
        moved.leader_offsets,
    )
    if algorithm == 3:
        assert path[0][1] == pytest.approx(0)
        assert path[1] == pytest.approx((2, 2))
    else:
        assert all(
            abs(a[0] - b[0]) <= 1e-9 or abs(a[1] - b[1]) <= 1e-9
            for a, b in zip(path[:-2], path[1:-1], strict=True)
        )
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


def test_recorded_datum_box_updates_when_selecting_a_new_text_style(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.formats.dxf_datum import datum_box_dimensions

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    style = TextStyle("datum-large", "大基准", height_mm=7)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 10), (20, 0), layout_mode="shared", box_size_mm=(5.3, 5)
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        datum.datum_id,
        "datum",
        {datum.datum_id},
    )
    monkeypatch.setattr(QInputDialog, "getItem", _text_response("大基准 (datum-large)"))
    window.act_datum_text_style.trigger()
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.text_style_id == "datum-large"
    assert updated.box_size_mm == pytest.approx(datum_box_dimensions("A", style))
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


def test_recorded_datum_box_updates_after_label_edit(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle
    from mycad.formats.dxf_datum import datum_box_dimensions

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 10), (20, 0), layout_mode="shared", box_size_mm=(5.3, 5)
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    editor.canvas.set_tool("选择元素")
    monkeypatch.setattr(QInputDialog, "getText", _text_response("LONGNAME"))
    QTest.mouseDClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=tools.datum_screen_bounds(datum).center().toPoint(),
    )
    changed = services.kernel.drawing_datum_identifiers[0]
    assert changed.label == "LONGNAME"
    assert changed.box_size_mm == pytest.approx(datum_box_dimensions("LONGNAME", TextStyle()))
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


def test_shared_text_style_change_recomputes_recorded_datum_box(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.formats.dxf_datum import datum_box_dimensions

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None and editor.canvas.text_tools is not None
    style = TextStyle("custom", "基准样式", height_mm=3.5)
    styles = TextStyleTable((TextStyle(), style))
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local")
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 10),
        (20, 0),
        text_style_id="custom",
        layout_mode="shared",
        box_size_mm=datum_box_dimensions("A", style),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    changed = replace(style, height_mm=7)
    new_styles = TextStyleTable((TextStyle(), changed))
    text_tools = editor.canvas.text_tools
    assert text_tools.execute is not None
    assert text_tools.execute("drawing.text_styles.set", new_styles.to_mapping())
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.box_size_mm == pytest.approx(datum_box_dimensions("A", changed))
    assert services.kernel.drawing_text_styles == new_styles
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)
    assert services.kernel.drawing_text_styles == styles


@pytest.mark.parametrize("algorithm", [3, 4])
def test_shared_text_style_reflows_box_aware_datum_and_undoes(
    qtbot: QtBot, tmp_path: Path, algorithm: int
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance_geometry import reroute_leader_around_box
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.formats.dxf_datum import datum_box_dimensions

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None and editor.canvas.text_tools is not None
    style = TextStyle("custom", "基准样式", height_mm=3.5)
    styles = TextStyleTable((TextStyle(), style))
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local", version=1)
    line = LineEntity(uuid4().hex, (30, 0), (30, 20))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 0),
        (30, 0),
        text_style_id="custom",
        layout_mode="shared",
        box_size_mm=datum_box_dimensions("A", style),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=(
            reroute_leader_around_box(
                (0, 0),
                ((20, 0),),
                (20, 0),
                (30, 0),
                (0, 0, *datum_box_dimensions("A", style)[:1], -datum_box_dimensions("A", style)[1]),
                orthogonal_box_side=True,
            )
            if algorithm == 4
            else ((20, 0),)
        ),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=algorithm,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()]},
        "local",
        version=26 if algorithm == 3 else 27,
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    changed = replace(style, height_mm=7)
    new_styles = TextStyleTable((TextStyle(), changed))
    text_tools = editor.canvas.text_tools
    assert text_tools.execute is not None
    assert text_tools.execute("drawing.text_styles.set", new_styles.to_mapping())
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.box_size_mm == pytest.approx(datum_box_dimensions("A", changed))
    assert updated.route_algorithm_version == algorithm and updated.leader_auto_normal
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)
    assert services.kernel.drawing_text_styles == styles
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (updated,), timeout=10000)
    path = tmp_path / "style-reflow.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_text_styles == new_styles


@pytest.mark.parametrize("algorithm", [3, 4])
def test_mixed_paste_reflows_recorded_box_with_renamed_style(
    qtbot: QtBot, monkeypatch: MonkeyPatch, algorithm: int
) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_geometry import reroute_leader_around_box
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.formats.dxf_datum import datum_box_dimensions

    services = app.build_app(discoverers=())
    session = DocumentSession()
    window = MainWindow(services=services, document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None and session.active is not None
    source = session.active.services
    source_style = TextStyle("custom", "来源", height_mm=3.5)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), source_style)).to_mapping(), "local"
    )
    line = LineEntity(uuid4().hex, (30, 0), (30, 20))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(source, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 0),
        (30, 0),
        text_style_id="custom",
        layout_mode="shared",
        box_size_mm=datum_box_dimensions("A", source_style),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=(
            reroute_leader_around_box(
                (0, 0),
                ((20, 0),),
                (20, 0),
                (30, 0),
                (
                    0,
                    0,
                    datum_box_dimensions("A", source_style)[0],
                    -datum_box_dimensions("A", source_style)[1],
                ),
                orthogonal_box_side=True,
            )
            if algorithm == 4
            else ((20, 0),)
        ),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=algorithm,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    editor.canvas.selected_entity_ids = {line.entity_id}
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    assert tools.copy_frame_to_clipboard()
    window.act_new_drawing.trigger()
    target, target_loaded = window.active_sketch_dialog(), window.loaded_document()
    assert target is not None and target_loaded is not None and session.active is not None
    conflicting = TextStyle("custom", "目标", height_mm=9)
    target_loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), conflicting)).to_mapping(), "local"
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    monkeypatch.setattr(QInputDialog, "getText", _text_response("LONG"))
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((40, 40))
    )
    kernel = session.active.services.kernel
    assert len(kernel.drawing_datum_identifiers) == 1, target.status_label.text()
    copied = kernel.drawing_datum_identifiers[0]
    assert copied.label == "LONG" and copied.text_style_id != "custom"
    assert copied.box_size_mm == pytest.approx(datum_box_dimensions("LONG", source_style))
    assert copied.route_algorithm_version == algorithm and copied.attachment is not None


def test_datumlabel_uses_same_target_first_flow_as_toolbar(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    calls: list[str] = []

    def ask(*_args: object, **kwargs: object) -> tuple[str, bool]:
        calls.append(str(kwargs.get("text", "")))
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", ask)
    bar = editor.drawing_command_bar.input
    count = loaded.document.command_count
    bar.setText("DATUMLABEL")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert tools.mechanical_datum_active and not calls
    QTest.keyClick(bar, Qt.Key.Key_Escape)
    assert not tools.pending and loaded.document.command_count == count and not calls
    bar.setText("DATUMLABEL")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    assert not calls
    QTest.keyClick(bar, Qt.Key.Key_Escape)
    assert not tools.pending and loaded.document.command_count == count and not calls
    bar.setText("DATUMLABEL")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    assert not calls
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    assert calls == ["A"]
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.target_mm == pytest.approx((0, 0))
    assert datum.position_mm == pytest.approx((10, 10))
    assert not tools.pending
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_datum_identifiers
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_frame_arrow_shape_uses_recorded_style_without_changing_legacy(qtbot: QtBot) -> None:
    import math
    from dataclasses import replace
    from uuid import uuid4

    from PySide6.QtGui import QPolygonF

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    legacy = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (0, 20),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -5),
    )
    modern = replace(legacy, leader_arrow_style="closed_filled")
    points = tools.frame_screen_leader(legacy)
    arrow = cast(
        "Callable[[FeatureControlFrame, tuple[QPointF, ...]], QPolygonF]",
        _private_member(tools, "_frame_screen_arrow"),
    )
    legacy_arrow = arrow(legacy, points)
    modern_arrow = arrow(modern, points)
    assert legacy_arrow.size() == modern_arrow.size() == 3
    legacy_width = math.hypot(
        legacy_arrow.at(1).x() - legacy_arrow.at(2).x(),
        legacy_arrow.at(1).y() - legacy_arrow.at(2).y(),
    )
    modern_width = math.hypot(
        modern_arrow.at(1).x() - modern_arrow.at(2).x(),
        modern_arrow.at(1).y() - modern_arrow.at(2).y(),
    )
    assert modern_width / legacy_width == pytest.approx((1 / 3) / 0.8)


def test_legacy_frame_export_anchor_matches_subpixel_screen_leader(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10.137, 20.321),
        rotation_deg=31,
        leader_target_mm=(0.237, 0.413),
        leader_offsets=((-6.314, -4.291),),
    )
    frame_anchor = cast(
        "Callable[[FeatureControlFrame], tuple[float, float] | None]",
        _private_member(tools, "_frame_leader_anchor"),
    )
    anchor = frame_anchor(frame)
    assert anchor is not None
    screen_anchor = editor.canvas.local_to_screen_precise(anchor)
    painted_anchor = tools.frame_screen_leader(frame)[0]
    assert painted_anchor.x() == pytest.approx(screen_anchor.x(), abs=1e-7)
    assert painted_anchor.y() == pytest.approx(screen_anchor.y(), abs=1e-7)


@pytest.mark.parametrize("rotation", [0, 31, 180])
def test_shared_legacy_frame_layout_matches_canvas(qtbot: QtBot, rotation: float) -> None:
    from uuid import uuid4

    from mycad.ui.geometric_tolerance_layout import legacy_frame_leader_layout

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20.1, 20.3),
        rotation_deg=rotation,
        leader_target_mm=(-20.1, -20.2),
        leader_offsets=((1, -1), (-10, -5)),
    )
    result = legacy_frame_leader_layout(frame, tools.manager)
    assert result is not None
    anchor, skipped = result
    frame_anchor = cast(
        "Callable[[FeatureControlFrame], tuple[float, float] | None]",
        _private_member(tools, "_frame_leader_anchor"),
    )
    assert anchor == pytest.approx(frame_anchor(frame))
    assert skipped == len(frame.leader_offsets) + 2 - len(tools.frame_screen_leader(frame))


def test_cli_legacy_frame_export_uses_same_layout_as_canvas(
    qtbot: QtBot, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from uuid import uuid4

    from mycad.cli.session import CliSession

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        rotation_deg=27,
        leader_target_mm=(0, 0),
        leader_offsets=((1, -1), (-10, -5)),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    expected = tools.legacy_frame_export_anchors((frame,))[frame.frame_id]
    expected_skips = tools.legacy_frame_export_skipped_vertices(
        (frame,), {frame.frame_id: expected}
    )
    revision = loaded.document.revision
    target = tmp_path / "cli-legacy.dxf"
    assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 0
    assert "字体" in capsys.readouterr().out
    imported = read_sketch_dxf(target).tolerance_frames[0]
    assert imported.leader_anchor_offset == pytest.approx(expected)
    assert imported.leader_offsets == frame.leader_offsets[expected_skips.get(frame.frame_id, 0) :]
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert loaded.document.revision == revision


def test_cli_legacy_datum_and_frame_use_canvas_font_geometry(
    qtbot: QtBot, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement
    from ezdxf.document import Drawing

    from mycad.cli.session import CliSession
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    style = TextStyle("wide", "宽字", font_family="DejaVu Sans", height_mm=5.5, width_factor=1.8)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    datum = DatumIdentifier(uuid4().hex, "B8", (10, 10), (55, 0), text_style_id="wide")
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (30, 30), leader_target_mm=(0, 0)
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    expected = tools.legacy_datum_export_snapshots((datum,))[datum.datum_id]
    anchor = tools.legacy_frame_export_anchors((frame,))[frame.frame_id]
    revision = loaded.document.revision
    path = tmp_path / "cli-datum.dxf"
    assert CliSession(services, doc=loaded).execute_line(f"export {path}") == 0
    assert "画布当前字体测量" in capsys.readouterr().out
    readfile = cast("Callable[[Path], Drawing]", vars(filemanagement)["readfile"])
    document = readfile(path)
    insert = cast("Any", next(iter(document.modelspace().query("INSERT"))))
    lines: list[Any] = list(cast("Any", document.blocks).get(insert.dxf.name).query("LINE"))
    assert float(lines[-4].dxf.end.x) == pytest.approx(expected.width)
    assert -float(lines[-3].dxf.end.y) == pytest.approx(expected.height)
    imported = read_sketch_dxf(path)
    assert imported.datum_identifiers[0].datum_id == datum.datum_id
    assert imported.tolerance_frames[0].leader_anchor_offset == pytest.approx(anchor)
    assert loaded.document.revision == revision


def test_legacy_datum_exports_through_real_cli_script(qtbot: QtBot, tmp_path: Path) -> None:
    import os
    import subprocess
    import sys
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement
    from ezdxf.document import Drawing

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    style = TextStyle("wide", "宽字", font_family="DejaVu Sans", height_mm=5.5, width_factor=1.8)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    datum = DatumIdentifier(uuid4().hex, "B8", (10, 10), (55, 0), text_style_id="wide")
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    expected = tools.legacy_datum_export_snapshots((datum,))[datum.datum_id]
    archive, target, script = (
        tmp_path / "datum.my2d",
        tmp_path / "datum.dxf",
        tmp_path / "export.txt",
    )
    save_document(loaded.document, archive)
    script.write_text(f"open {archive}\nexport {target}\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-m", "mycad.cli", "run", str(script)],
        capture_output=True,
        encoding="utf-8",
        timeout=45,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "画布当前字体测量" in result.stdout
    readfile = cast("Callable[[Path], Drawing]", vars(filemanagement)["readfile"])
    document = readfile(target)
    insert = cast("Any", next(iter(document.modelspace().query("INSERT"))))
    lines: list[Any] = list(cast("Any", document.blocks).get(insert.dxf.name).query("LINE"))
    assert float(lines[-4].dxf.end.x) == pytest.approx(expected.width)
    assert -float(lines[-3].dxf.end.y) == pytest.approx(expected.height)
    assert read_sketch_dxf(target).datum_identifiers[0].datum_id == datum.datum_id


def test_cli_legacy_datum_reports_font_substitution(
    qtbot: QtBot, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from uuid import uuid4

    from mycad.cli.session import CliSession
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("missing", "缺失字体", font_family="MyCAD Missing Font 999999")
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0), text_style_id="missing")
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    target = tmp_path / "missing-font.dxf"
    assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 0
    output = capsys.readouterr().out
    assert datum.datum_id[:8] in output and "不可用" in output
    assert read_sketch_dxf(target).datum_identifiers[0].datum_id == datum.datum_id


def test_cli_legacy_frame_export_reports_font_substitution(
    qtbot: QtBot, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from uuid import uuid4

    from mycad.cli.session import CliSession
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    style = TextStyle("missing", "图纸字体", font_family="MyCAD-Definitely-Not-Installed")
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        text_style_id="missing",
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    target = tmp_path / "cli-missing-font.dxf"
    assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 0
    assert "MyCAD-Definitely-Not-Installed" in capsys.readouterr().out
    assert read_sketch_dxf(target).tolerance_frames[0].text_style_id == "missing"


def test_cli_legacy_export_loads_canvas_imported_font_directory(
    qtbot: QtBot, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from uuid import uuid4

    from ezdxf.fonts.font_manager import FONT_DIRECTORIES

    from mycad.cli.session import CliSession
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.ui.font_manager import FontManager

    roots = [Path(path).expanduser() for values in FONT_DIRECTORIES.values() for path in values]
    source = next((p for root in roots if root.is_dir() for p in root.rglob("*.ttf")), None)
    if source is None:
        pytest.skip("No installed TrueType font available as an import fixture")
    font = tmp_path / "MyCADImportedFont.ttf"
    font.write_bytes(source.read_bytes())
    manager = FontManager(tmp_path / "imported")
    manager.import_font(font)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    style = TextStyle("imported", "自带字体", font_file=font.name)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        text_style_id="imported",
    )
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0), text_style_id="imported")
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    target = tmp_path / "imported-font.dxf"
    cli = CliSession(services, doc=loaded, font_resource_directory=manager.directory)
    assert cli.execute_line(f"export {target}") == 0
    assert "MyCADImportedFont.ttf 不可用" not in capsys.readouterr().out
    imported = read_sketch_dxf(target)
    assert imported.tolerance_frames[0].text_style_id == "imported"
    assert imported.datum_identifiers[0].text_style_id == "imported"


def test_embedded_cli_exports_with_canvas_imported_font(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement
    from ezdxf.document import Drawing
    from ezdxf.fonts.font_manager import FONT_DIRECTORIES

    from mycad.core.drawing_text import TextStyle, TextStyleTable

    roots = [Path(path).expanduser() for values in FONT_DIRECTORIES.values() for path in values]
    source = next((p for root in roots if root.is_dir() for p in root.rglob("*.ttf")), None)
    if source is None:
        pytest.skip("No installed TrueType font available as an import fixture")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    font = tmp_path / "MyCADEmbeddedFont.ttf"
    font.write_bytes(source.read_bytes())
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, tab = window.active_sketch_dialog(), window.loaded_document(), window.cli_tab
    assert editor is not None and loaded is not None and tab is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.manager.import_font(font)
    style = TextStyle("imported", "自带字体", font_file=font.name)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        text_style_id="imported",
    )
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0), text_style_id="imported")
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    expected = tools.legacy_frame_export_anchors((frame,))[frame.frame_id]
    datum_box = tools.legacy_datum_export_snapshots((datum,))[datum.datum_id]
    target = tmp_path / "embedded-cli.dxf"
    rc, messages = tab.dispatch_line(f"export {target}")
    assert rc == 0
    assert "MyCADEmbeddedFont.ttf 不可用" not in " ".join(messages)
    assert read_sketch_dxf(target).tolerance_frames[0].leader_anchor_offset == pytest.approx(
        expected
    )
    readfile = cast("Callable[[Path], Drawing]", vars(filemanagement)["readfile"])
    document = readfile(target)
    insert = cast("Any", next(iter(document.modelspace().query("INSERT"))))
    lines: list[Any] = list(cast("Any", document.blocks).get(insert.dxf.name).query("LINE"))
    assert float(lines[-4].dxf.end.x) == pytest.approx(datum_box.width)
    assert -float(lines[-3].dxf.end.y) == pytest.approx(datum_box.height)


def test_standalone_cli_uses_desktop_default_font_resource_directory(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys
    from uuid import uuid4

    from ezdxf.fonts.font_manager import FONT_DIRECTORIES

    from mycad.cli.session import CliSession
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.ui.font_manager import FontManager

    if sys.platform != "linux":
        pytest.skip("This isolated font-directory fixture uses XDG_DATA_HOME")
    roots = [Path(path).expanduser() for values in FONT_DIRECTORIES.values() for path in values]
    source = next((p for root in roots if root.is_dir() for p in root.rglob("*.ttf")), None)
    if source is None:
        pytest.skip("No installed TrueType font available as an import fixture")
    data = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    font = tmp_path / "MyCADStandaloneFont.ttf"
    font.write_bytes(source.read_bytes())
    FontManager(data / Path(sys.argv[0]).name / "MyCAD" / "fonts").import_font(font)
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("imported", "自带字体", font_file=font.name)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        text_style_id="imported",
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    target = tmp_path / "standalone-cli.dxf"
    assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 0
    assert "MyCADStandaloneFont.ttf 不可用" not in capsys.readouterr().out


def test_legacy_frame_exports_through_real_cli_script(qtbot: QtBot, tmp_path: Path) -> None:
    import os
    import subprocess
    import sys
    from uuid import uuid4

    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    archive = tmp_path / "legacy.my2d"
    target = tmp_path / "legacy.dxf"
    script = tmp_path / "export.txt"
    save_document(loaded.document, archive)
    script.write_text(f"open {archive}\nexport {target}\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-m", "mycad.cli", "run", str(script)],
        capture_output=True,
        encoding="utf-8",
        timeout=45,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "字体" in result.stdout
    imported = read_sketch_dxf(target).tolerance_frames[0]
    assert imported.leader_anchor_offset is not None
    assert imported.leader_target_mm == frame.leader_target_mm


@pytest.mark.parametrize("with_vertex", [False, True])
def test_cli_legacy_surface_frame_export_uses_canvas_layout_and_retains_surface(
    qtbot: QtBot, tmp_path: Path, with_vertex: bool
) -> None:
    from uuid import uuid4

    from mycad.cli.session import CliSession
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    style = TextStyle("large", "大字", height_mm=5.5, width_factor=1.2)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    indication = SurfaceIndication((5, 8), (15, 8), 0.5, ((2, 3),), arrow_size_mm=3)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (35, 30),
        rotation_deg=37,
        leader_target_mm=(0, 0),
        leader_offsets=((-10, -5),) if with_vertex else (),
        surface_indication=indication,
        text_style_id="large",
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    anchor = tools.legacy_frame_export_anchors((frame,))[frame.frame_id]
    target = tmp_path / "legacy-surface.dxf"
    assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 0
    imported = read_sketch_dxf(target).tolerance_frames[0]
    assert imported.leader_anchor_offset == pytest.approx(anchor)
    assert imported.leader_target_mm == frame.leader_target_mm
    assert imported.leader_offsets == frame.leader_offsets
    assert imported.surface_indication == indication
    assert imported.text_style_id == "large"
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_cli_legacy_worker_uses_utf8_under_non_utf8_parent_environment(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.cli.session import CliSession
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("missing", "图纸字体", font_family="MyCAD-Definitely-Not-Installed")
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        text_style_id="missing",
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    target = tmp_path / "中文图纸.dxf"
    messages: list[str] = []
    assert CliSession(services, doc=loaded, messages=messages).execute_line(f"export {target}") == 0
    assert any("MyCAD-Definitely-Not-Installed" in message for message in messages)
    assert read_sketch_dxf(target).tolerance_frames[0].text_style_id == "missing"


def test_cli_legacy_worker_reports_overlapping_target_without_overwriting(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from uuid import uuid4

    from mycad.cli.session import CliSession

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (0, 0),
        leader_target_mm=(1, -2),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    target = tmp_path / "existing.dxf"
    target.write_bytes(b"original")
    messages: list[str] = []
    assert CliSession(services, doc=loaded, messages=messages).execute_line(f"export {target}") == 1
    assert any("无法计算框侧锚点" in message for message in messages)
    assert target.read_bytes() == b"original"


@pytest.mark.parametrize("auto_route", [False, True])
def test_cli_legacy_frame_exports_hidden_box_vertex_with_normal_attachment(
    qtbot: QtBot, tmp_path: Path, auto_route: bool
) -> None:
    from uuid import uuid4

    from mycad.cli.session import CliSession
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((1, -3), (-20, -15)),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=auto_route,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    anchors = tools.legacy_frame_export_anchors((frame,))
    assert tools.legacy_frame_export_skipped_vertices((frame,), anchors) == {frame.frame_id: 1}
    target = tmp_path / "normal.dxf"
    assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 0
    imported = read_sketch_dxf(target).tolerance_frames[0]
    assert imported.leader_offsets == (frame.leader_offsets if auto_route else ((-20, -15),))
    assert imported.leader_attachment == attachment and imported.leader_auto_normal
    assert imported.leader_auto_route is auto_route
    assert services.kernel.drawing_tolerance_frames == (frame,)


@pytest.mark.parametrize("source", ["gui", "cli"])
def test_legacy_auto_route_with_text_cell_vertex_exports_via_user_entry(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch, source: str
) -> None:
    from uuid import uuid4

    from PySide6.QtWidgets import QFileDialog

    from mycad.cli.session import CliSession
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((8, -3), (-20, -15)),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    from mycad.ui.geometric_tolerance_layout import FrameLayout

    frame_layout = cast(
        "Callable[[FeatureControlFrame], FrameLayout]", _private_member(tools, "_layout")
    )
    assert frame_layout(frame).bounds.width() > 8
    target = tmp_path / "text-cell-route.dxf"
    if source == "gui":
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", _save_response(str(target), "DXF 草图 (*.dxf)")
        )
        monkeypatch.setattr(DxfOutputPreviewDialog, "exec", _accept_preview)
        window.act_export.trigger()
        qtbot.waitUntil(target.exists, timeout=20000)
    else:
        assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 0
    assert read_sketch_dxf(target).tolerance_frames == (frame,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


@pytest.mark.parametrize("angle", [37.0, 180.0])
def test_cli_auto_route_layout_snapshot_handles_rotation_and_multiple_rows(
    qtbot: QtBot, tmp_path: Path, angle: float
) -> None:
    import math
    from uuid import uuid4

    from mycad.cli.session import CliSession
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    hidden = (8 * cosine + 9 * sine, 8 * sine - 9 * cosine)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2), ToleranceRow("flatness", 0.2, 2)),
        (20, 20),
        rotation_deg=angle,
        leader_target_mm=(0, 0),
        leader_offsets=(hidden, (-20, -15)),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    anchors = tools.legacy_frame_export_anchors((frame,))
    assert tools.legacy_frame_export_skipped_vertices((frame,), anchors) == {frame.frame_id: 1}
    target = tmp_path / "rotated-multiline.dxf"
    assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 0
    assert read_sketch_dxf(target).tolerance_frames == (frame,)


@pytest.mark.parametrize("source", ["gui", "cli"])
def test_legacy_hidden_normal_exports_via_user_entry(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch, source: str
) -> None:
    from uuid import uuid4

    from PySide6.QtWidgets import QFileDialog

    from mycad.cli.session import CliSession
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (-3, -2), (7, -2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (0, 6),
        leader_target_mm=(2, -2),
        leader_offsets=((2, -3),),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    anchors = tools.legacy_frame_export_anchors((frame,))
    assert tools.legacy_frame_export_skipped_vertices((frame,), anchors) == {frame.frame_id: 1}
    target = tmp_path / "hidden-normal.dxf"
    if source == "gui":
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", _save_response(str(target), "DXF 草图 (*.dxf)")
        )
        monkeypatch.setattr(DxfOutputPreviewDialog, "exec", _accept_preview)
        window.act_export.trigger()
        qtbot.waitUntil(target.exists, timeout=20000)
    else:
        assert CliSession(services, doc=loaded).execute_line(f"export {target}") == 0
    assert read_sketch_dxf(target).tolerance_frames == (frame,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_fit_view_includes_visible_frames_datums_and_leaders(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QRectF

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (500, 300),
        rotation_deg=37,
        leader_target_mm=(570, 330),
        leader_anchor_offset=(4, -2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (515, 260), (540, 240))
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    view_state = cast(
        "Callable[[], tuple[float, float, float]]", _private_member(canvas, "_view_state")
    )
    previous_view = view_state()
    canvas.fit_view()
    viewport = QRectF(canvas.rect()).adjusted(5, 5, -5, -5)
    assert viewport.contains(tools.screen_bounds(frame))
    assert viewport.contains(tools.datum_screen_bounds(datum))
    assert all(viewport.contains(p) for p in tools.frame_screen_leader(frame))
    assert all(viewport.contains(p) for p in tools.datum_screen_path(datum)[0])
    assert canvas.restore_previous_view()
    assert view_state() == previous_view


def test_fit_view_ignores_hidden_annotations_but_includes_locked_and_reference(
    qtbot: QtBot,
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QRectF

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.detached_dimension_layout import layout_reference_dimension

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    layers = canvas.layer_table.add(SketchLayer("locked", locked=True)).add(
        SketchLayer("hidden", visible=False)
    )
    canvas.set_layer_table(layers, "0")
    canvas.document_layer_table = layers
    hidden_line = LineEntity(uuid4().hex, (100000, 100000), (100010, 100000), layer_name="hidden")
    canvas.entities = [hidden_line]
    canvas.constraints = [
        SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(hidden_line.entity_id, "geometry"),),
            10,
            "mm",
            position_mm=(100000, 100010),
            layer_name="hidden",
        )
    ]
    assert canvas.text_tools is not None
    canvas.text_tools.sync(
        (DrawingText(uuid4().hex, "隐藏文字", (100000, 100020), layer_name="hidden"),),
        canvas.text_tools.styles,
    )
    visible = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (500, 300), layer_name="locked"
    )
    hidden = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (100000, 100000), layer_name="hidden"
    )
    dimension = DetachedDimension(uuid4().hex, "aligned", (480, 280), (500, 280), (480, 270), 0, 20)
    tools.sync((visible, hidden), (), (dimension,))
    canvas.fit_view()
    viewport = QRectF(canvas.rect()).adjusted(5, 5, -5, -5)
    assert viewport.contains(tools.screen_bounds(visible))
    assert viewport.contains(layout_reference_dimension(dimension, canvas).label)
    assert not viewport.contains(tools.screen_bounds(hidden))
    assert canvas.view_scale > 1


def test_fit_view_includes_surface_reference_and_second_leader(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QRectF

    from mycad.core.geometric_tolerance import SurfaceIndication

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    indication = SurfaceIndication((200, 150), (230, 150), 0.5, ((180, 70),))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20, 20),
        leader_target_mm=(10, 10),
        surface_indication=indication,
    )
    tools.sync((frame,), ())
    canvas.fit_view()
    viewport = QRectF(canvas.rect()).adjusted(5, 5, -5, -5)
    assert viewport.contains(tools.screen_bounds(frame))
    surface_path = cast(
        "Callable[[tuple[float, float], SurfaceIndication], QPainterPath]",
        _private_member(tools, "_surface_indication_path"),
    )
    assert viewport.contains(surface_path((10, 10), indication).boundingRect())


def test_fit_view_includes_surface_extension(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QRectF

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    canvas.associative_sketches_provider = lambda: (sketch,)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 500),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (15, 0), attachment=attachment)
    tools.sync((), (datum,))
    canvas.fit_view()
    viewport = QRectF(canvas.rect()).adjusted(5, 5, -5, -5)
    points = tools.surface_screen_path(attachment)
    assert len(points) >= 2
    assert all(viewport.contains(point) for point in points)


def test_fit_view_restores_view_if_annotation_measurement_fails(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.zoom_view_factor(0.25 / canvas.view_scale)
    view_state = cast(
        "Callable[[], tuple[float, float, float]]", _private_member(canvas, "_view_state")
    )
    before = view_state()

    def fail() -> tuple[tuple[float, float], ...]:
        raise ValueError("simulated measurement failure")

    monkeypatch.setattr(tools, "visible_extent_points", fail)
    with pytest.raises(ValueError, match="simulated"):
        canvas.fit_view()
    assert view_state() == before


def test_fit_view_finds_legacy_datum_when_starting_extremely_zoomed_out(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QRectF

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(uuid4().hex, "A", (500, 300), (540, 240))
    tools.sync((), (datum,))
    canvas.zoom_view_factor(1e-6 / canvas.view_scale)
    canvas.fit_view()
    viewport = QRectF(canvas.rect()).adjusted(5, 5, -5, -5)
    assert viewport.contains(tools.datum_screen_bounds(datum))
    assert all(viewport.contains(point) for point in tools.datum_screen_path(datum)[0])


def test_fit_view_finds_reference_dimension_when_starting_extremely_zoomed_out(
    qtbot: QtBot,
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QRectF

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.detached_dimension_layout import layout_reference_dimension

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    dimension = DetachedDimension(uuid4().hex, "aligned", (500, 300), (540, 300), (500, 280), 0, 40)
    tools.sync((), (), (dimension,))
    canvas.zoom_view_factor(1e-6 / canvas.view_scale)
    canvas.fit_view()
    viewport = QRectF(canvas.rect()).adjusted(5, 5, -5, -5)
    layout = layout_reference_dimension(dimension, canvas)
    assert viewport.contains(layout.label)
    assert all(viewport.contains(point) for segment in layout.lines for point in segment)
    assert canvas.view_scale > 1


def test_fit_view_finds_sketch_dimension_when_starting_extremely_zoomed_out(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QRectF

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (500, 300), (540, 300))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        40,
        "mm",
        position_mm=(500, 260),
    )
    canvas.entities = [line]
    canvas.constraints = [dimension]
    canvas.zoom_view_factor(1e-6 / canvas.view_scale)
    canvas.fit_view()
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    viewport = QRectF(canvas.rect()).adjusted(5, 5, -5, -5)
    assert viewport.contains(layout.label)
    assert viewport.contains(canvas.dimension_label_rect(dimension, layout.label))
    assert all(viewport.contains(point) for segment in layout.lines for point in segment)
    assert canvas.view_scale > 1


@pytest.mark.parametrize("layout_mode", ["legacy", "shared", "shared_auto"])
def test_graphic_datum_uses_filled_canvas_glyphs_and_geometry(
    qtbot: QtBot, tmp_path: Path, layout_mode: str
) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.formats.dxf_datum import datum_box_dimensions
    from mycad.formats.dxf_preview import prepare_dxf_output_preview

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    style = TextStyle("wide", "宽字", font_family="DejaVu Sans", height_mm=5.5, width_factor=1.8)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "B8",
        (10.31, 10.17),
        (55, 0),
        text_style_id="wide",
        layout_mode="shared" if layout_mode == "shared_auto" else layout_mode,
        box_size_mm=datum_box_dimensions("B8", style) if layout_mode == "shared" else None,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    rect = tools.datum_screen_bounds(datum)
    width = rect.width() / editor.canvas.view_scale
    leader, arrow = tools.datum_screen_path(datum, rect)
    expected_leader = tuple(editor.canvas.screen_to_local(point) for point in leader)
    preview = prepare_dxf_output_preview(
        services.kernel,
        tolerance_graphics=True,
        graphic_datum_snapshots=tools.graphic_datum_export_snapshots((datum,)),
    )
    path = tmp_path / "datum.dxf"
    preview.write(path)
    readfile = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    document = readfile(path)
    insert = list(document.modelspace().query("INSERT"))[0]
    assert not insert.has_xdata("MYCAD_DATUM")
    block = document.blocks.get(insert.dxf.name)
    assert not block.query("TEXT")
    glyphs = list(block.query("HATCH"))
    assert len(glyphs) == 2
    assert all(len(glyph.paths) > 1 for glyph in glyphs)
    lines = list(block.query("LINE"))
    assert any(tuple(line.dxf.start)[:2] == pytest.approx((width, 0)) for line in lines)
    assert any(
        tuple(line.dxf.end)[:2]
        == pytest.approx(
            (
                expected_leader[-1][0] - datum.position_mm[0],
                expected_leader[-1][1] - datum.position_mm[1],
            )
        )
        for line in lines
    )
    solid = list(block.query("SOLID"))[0]
    for index in range(arrow.size()):
        world = editor.canvas.screen_to_local(arrow.at(index))
        assert tuple(solid.dxf.get(f"vtx{index}"))[:2] == pytest.approx(
            (world[0] - datum.position_mm[0], world[1] - datum.position_mm[1])
        )
    assert any("基准" in warning and "无法恢复" in warning for warning in preview.report.warnings)
    assert not any(
        "基准文字样式" in warning and "其他 CAD 可能替代字体" in warning
        for warning in preview.report.warnings
    )
    assert not any("未取得画布基准字形快照" in warning for warning in preview.report.warnings)


def test_graphic_export_freezes_mixed_datum_and_frame_without_document_changes(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement
    from PySide6.QtWidgets import QFileDialog

    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    datum = DatumIdentifier(uuid4().hex, "B8", (10, 10), (35, 0))
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 25))
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    history = tuple(loaded.document.commands)
    target = tmp_path / "mixed.dxf"
    choice = "DXF 图形兼容（标注不可结构化编辑） (*.dxf)"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", _save_response(str(target), choice))
    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", _accept_preview)
    window.act_export.trigger()
    qtbot.waitUntil(target.exists, timeout=20000)
    readfile = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    document = readfile(target)
    modelspace = document.modelspace()
    assert not modelspace.query("TOLERANCE") and modelspace.query("HATCH")
    insert = list(modelspace.query("INSERT"))[0]
    assert not insert.has_xdata("MYCAD_DATUM")
    assert document.blocks.get(insert.dxf.name).query("HATCH")
    assert tuple(loaded.document.commands) == history


@pytest.mark.parametrize("layout_mode", ["legacy", "shared"])
def test_graphic_datum_snapshot_is_independent_of_view_scale_and_pan(
    qtbot: QtBot, layout_mode: str
) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle
    from mycad.formats.dxf_datum import datum_box_dimensions
    from mycad.formats.dxf_preview import prepare_dxf_output_preview

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(
        uuid4().hex,
        "B8",
        (10.31, 10.17),
        (55, 0),
        layout_mode=layout_mode,
        box_size_mm=datum_box_dimensions("B8", TextStyle()) if layout_mode == "shared" else None,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    initial = tools.graphic_datum_export_snapshots((datum,))[datum.datum_id]
    native_initial = tools.legacy_datum_export_snapshots((datum,))
    editor.canvas.zoom_view_factor(1e-6 / editor.canvas.view_scale)
    assert editor.canvas.pan_view_between((0, 0), (1e14, 1e14))
    remote = tools.graphic_datum_export_snapshots((datum,))[datum.datum_id]
    assert remote.width == pytest.approx(initial.width, abs=1e-9, rel=0)
    assert remote.height == pytest.approx(initial.height, abs=1e-9, rel=0)
    assert len(remote.leader) == len(initial.leader)
    for actual, expected in zip(remote.leader, initial.leader, strict=True):
        assert actual == pytest.approx(expected, abs=1e-9, rel=0)
    assert len(remote.arrow) == len(initial.arrow)
    for actual, expected in zip(remote.arrow, initial.arrow, strict=True):
        assert actual == pytest.approx(expected, abs=1e-9, rel=0)
    assert remote.glyphs == initial.glyphs
    assert tools.legacy_datum_export_snapshots((datum,)) == native_initial
    prepare_dxf_output_preview(
        services.kernel, tolerance_graphics=True, graphic_datum_snapshots={datum.datum_id: remote}
    )


def test_native_legacy_datum_export_matches_canvas_and_preserves_structure(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    style = TextStyle("wide", "宽字", font_family="DejaVu Sans", height_mm=5.5, width_factor=1.8)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "B8",
        (10.31, 10.17),
        (55, 0),
        text_style_id="wide",
        leader_offsets=((15, -3),),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    rect = tools.datum_screen_bounds(datum)
    leader, arrow = tools.datum_screen_path(datum, rect)
    preview = prepare_dxf_output_preview(
        services.kernel, legacy_datum_snapshots=tools.legacy_datum_export_snapshots((datum,))
    )
    path = tmp_path / "native.dxf"
    preview.write(path)
    readfile = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    document = readfile(path)
    insert = list(document.modelspace().query("INSERT"))[0]
    assert insert.has_xdata("MYCAD_DATUM")
    block = document.blocks.get(insert.dxf.name)
    lines = list(block.query("LINE"))
    assert float(lines[-4].dxf.end.x) == pytest.approx(rect.width() / editor.canvas.view_scale)
    assert -float(lines[-3].dxf.end.y) == pytest.approx(rect.height() / editor.canvas.view_scale)
    text = list(block.query("TEXT"))[0]
    assert float(text.dxf.insert.y) == pytest.approx(
        -(rect.height() / editor.canvas.view_scale + style.height_mm) / 2
    )
    for index, point in enumerate(leader[1:]):
        world = editor.canvas.screen_to_local(point)
        assert tuple(lines[index].dxf.end)[:2] == pytest.approx(
            (world[0] - datum.position_mm[0], world[1] - datum.position_mm[1])
        )
    solid = list(block.query("SOLID"))[0]
    assert arrow.size() == 3
    arrow_tip = editor.canvas.screen_to_local(arrow.at(0))
    assert tuple(solid.dxf.vtx0)[:2] == pytest.approx(
        (arrow_tip[0] - datum.position_mm[0], arrow_tip[1] - datum.position_mm[1])
    )
    native_vertices = tuple(tuple(solid.dxf.get(f"vtx{index}"))[:2] for index in range(3))
    for index in range(arrow.size()):
        world = editor.canvas.screen_to_local(arrow.at(index))
        relative = (world[0] - datum.position_mm[0], world[1] - datum.position_mm[1])
        assert any(vertex == pytest.approx(relative) for vertex in native_vertices)
    restored = read_sketch_dxf(path).datum_identifiers[0]
    assert restored.datum_id == datum.datum_id
    assert restored.position_mm == datum.position_mm
    assert restored.target_mm == datum.target_mm
    assert restored.leader_offsets == datum.leader_offsets
    assert restored.layout_mode == datum.layout_mode


def test_native_legacy_datum_without_leader_preserves_structure(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement

    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(uuid4().hex, "A", (3, 5), (3, -10), leader_visible=False)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    preview = prepare_dxf_output_preview(
        services.kernel, legacy_datum_snapshots=tools.legacy_datum_export_snapshots((datum,))
    )
    path = tmp_path / "no-leader.dxf"
    preview.write(path)
    readfile = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    doc = readfile(path)
    insert = list(doc.modelspace().query("INSERT"))[0]
    block = doc.blocks.get(insert.dxf.name)
    assert len(block.query("LINE")) == 4
    assert not block.query("SOLID")
    restored = read_sketch_dxf(path).datum_identifiers[0]
    assert restored.datum_id == datum.datum_id and not restored.leader_visible


def test_native_legacy_datum_snapshot_preserves_surface_attachment(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (15, 0), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    preview = prepare_dxf_output_preview(
        services.kernel, legacy_datum_snapshots=tools.legacy_datum_export_snapshots((datum,))
    )
    path = tmp_path / "attached.dxf"
    preview.write(path)
    result = read_sketch_dxf(path)
    restored = result.datum_identifiers[0]
    assert restored.attachment == attachment
    assert restored.target_mm == datum.target_mm
    assert not any("附着" in warning and "解除" in warning for warning in result.report.warnings)


def test_native_export_snapshots_mixed_legacy_and_shared_datums_without_history_changes(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement
    from PySide6.QtWidgets import QFileDialog

    from mycad.formats.providers.dxf_provider import read_sketch_dxf
    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    legacy = DatumIdentifier(uuid4().hex, "B8", (10, 10), (35, 0))
    shared = DatumIdentifier(
        uuid4().hex, "C", (30, 20), (50, 5), layout_mode="shared", box_size_mm=(10, 6)
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [legacy.to_mapping(), shared.to_mapping()]},
        "local",
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    canvas_width = tools.datum_screen_bounds(legacy).width() / editor.canvas.view_scale
    history = tuple(loaded.document.commands)
    target = tmp_path / "mixed-native.dxf"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", _save_response(str(target), "DXF 草图 (*.dxf)")
    )
    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", _accept_preview)
    window.act_export.trigger()
    qtbot.waitUntil(target.exists, timeout=20000)
    readfile = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    document = readfile(target)
    inserts = list(document.modelspace().query("INSERT"))
    assert len(inserts) == 2
    box = list(document.blocks.get(inserts[0].dxf.name).query("LINE"))[-4:]
    assert float(box[0].dxf.end.x) == pytest.approx(canvas_width)
    restored = read_sketch_dxf(target).datum_identifiers
    assert {item.datum_id for item in restored} == {legacy.datum_id, shared.datum_id}
    assert tuple(loaded.document.commands) == history


def test_native_legacy_datum_export_preserves_file_when_snapshot_is_missing(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from PySide6.QtWidgets import QFileDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    target = tmp_path / "existing.dxf"
    target.write_bytes(b"existing")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", _save_response(str(target), "DXF 草图 (*.dxf)")
    )

    def no_snapshots(_datums: tuple[DatumIdentifier, ...]) -> dict[str, object]:
        return {}

    monkeypatch.setattr(tools, "legacy_datum_export_snapshots", no_snapshots)
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", errors.append)
    window.act_export.trigger()
    qtbot.waitUntil(lambda: bool(errors), timeout=20000)
    assert "旧基准布局快照" in errors[0]
    assert target.read_bytes() == b"existing"


def test_graphic_datum_exports_literal_percent_and_caret_as_filled_glyphs(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement

    from mycad.formats.dxf_preview import prepare_dxf_output_preview

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier(uuid4().hex, "A%^", (0, 0), (0, -10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    preview = prepare_dxf_output_preview(
        services.kernel,
        tolerance_graphics=True,
        graphic_datum_snapshots=tools.graphic_datum_export_snapshots((datum,)),
    )
    path = tmp_path / "special.dxf"
    preview.write(path)
    readfile = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    document = readfile(path)
    insert = list(document.modelspace().query("INSERT"))[0]
    block = document.blocks.get(insert.dxf.name)
    assert len(block.query("HATCH")) == 3
    assert not block.query("TEXT")


def test_graphic_datum_reports_surface_extension_losing_its_owner(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.formats.dxf_preview import prepare_dxf_output_preview

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (15, 0), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    preview = prepare_dxf_output_preview(
        services.kernel,
        tolerance_graphics=True,
        graphic_datum_snapshots=tools.graphic_datum_export_snapshots((datum,)),
    )
    assert any("表面延伸线" in warning and "关联" in warning for warning in preview.report.warnings)


def test_graphic_snapshot_rejects_unavailable_glyph_paths(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.ui.text_layout import TextLayout

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0))
    monkeypatch.setattr(TextLayout, "glyph_paths", _no_glyph_paths)
    with pytest.raises(ValueError, match="轮廓不可用"):
        tools.graphic_frame_export_glyphs((frame,))


@pytest.mark.parametrize("owner", ["frame", "datum"])
def test_graphic_export_keeps_existing_file_when_glyphs_are_unavailable(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch, owner: str
) -> None:
    from uuid import uuid4

    from PySide6.QtWidgets import QFileDialog

    from mycad.ui.text_layout import TextLayout

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    if owner == "frame":
        frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0))
        payload = {"add_frames": [frame.to_mapping()]}
    else:
        datum = DatumIdentifier(uuid4().hex, "B8", (0, 0), (0, -10))
        payload = {"add_datums": [datum.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", payload, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"existing")
    choice = "DXF 图形兼容（标注不可结构化编辑） (*.dxf)"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", _save_response(str(path), choice))
    monkeypatch.setattr(TextLayout, "glyph_paths", _no_glyph_paths)
    messages: list[str] = []
    monkeypatch.setattr(window, "_show_error", messages.append)
    window.act_export.trigger()
    assert path.read_bytes() == b"existing"
    assert any("轮廓不可用" in message for message in messages)


def test_graphic_frame_snapshot_reports_font_substitution(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    style = TextStyle("missing", "缺失字体", font_family="MyCAD Missing Font 999999")
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2),), (10, 10), text_style_id="missing"
    )
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -10), text_style_id="missing")
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    notices = tools.graphic_frame_export_font_notices((frame,))
    assert any(frame.frame_id[:8] in message and "不可用" in message for message in notices)
    datum_notices = tools.graphic_datum_export_font_notices((datum,))
    assert any(datum.datum_id[:8] in message and "不可用" in message for message in datum_notices)
    legacy_notices = tools.legacy_datum_export_font_notices((datum,))
    assert any(datum.datum_id[:8] in message and "不可用" in message for message in legacy_notices)


def test_graphic_export_freezes_filled_shaped_text_with_holes(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement

    from mycad.formats.dxf_preview import prepare_dxf_output_preview

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(80, 7),
        leader_anchor_offset=(0, -3),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    preview = prepare_dxf_output_preview(
        services.kernel,
        tolerance_graphics=True,
        graphic_frame_widths=tools.graphic_frame_export_widths((frame,)),
        graphic_frame_glyphs=tools.graphic_frame_export_glyphs((frame,)),
    )
    path = tmp_path / "filled.dxf"
    preview.write(path)
    readfile = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    space = readfile(path).modelspace()
    assert not space.query("TEXT")
    glyphs = list(space.query("HATCH"))
    assert len(glyphs) == 4
    assert any(len(glyph.paths) > 1 for glyph in glyphs)
    assert not any("字体替代可能导致文字溢出" in warning for warning in preview.report.warnings)


def test_graphic_frame_right_edge_matches_canvas_leader_anchor(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from dataclasses import replace
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement
    from PySide6.QtWidgets import QFileDialog

    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2),), (10, 10), leader_target_mm=(80, 7)
    )
    from mycad.ui.geometric_tolerance_layout import FrameLayout

    frame_layout = cast(
        "Callable[[FeatureControlFrame], FrameLayout]", _private_member(tools, "_layout")
    )
    width = frame_layout(frame).bounds.width()
    frame = replace(frame, leader_anchor_offset=(width, -3))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    target = tmp_path / "graphic-frame.dxf"
    choice = "DXF 图形兼容（标注不可结构化编辑） (*.dxf)"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", _save_response(str(target), choice))
    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", _accept_preview)
    window.act_export.trigger()
    qtbot.waitUntil(target.exists, timeout=20000)
    readfile = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    space = readfile(target).modelspace()
    assert any(
        abs(line.dxf.start.x - (10 + width)) < 1e-7
        and abs(line.dxf.end.x - (10 + width)) < 1e-7
        and sorted((line.dxf.start.y, line.dxf.end.y)) == pytest.approx([4, 10])
        for line in space.query("LINE")
    )
    assert tuple(space.query("LEADER")[0].vertices[-1])[:2] == pytest.approx((10 + width, 7))


@pytest.mark.parametrize("angle", [0.0, 37.0, 180.0])
def test_graphic_frame_cells_match_canvas_for_rotated_multiline_custom_style(
    qtbot: QtBot, tmp_path: Path, angle: float
) -> None:
    import math
    from uuid import uuid4

    import ezdxf.filemanagement as filemanagement

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumReference
    from mycad.formats.dxf_preview import prepare_dxf_output_preview

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    style = TextStyle("wide", "宽字", height_mm=5.5, width_factor=1.8)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (
            ToleranceRow("position", 0.1, 2, True, "M", (DatumReference("A"),)),
            ToleranceRow("flatness", 0.2, 2),
        ),
        (20, 30),
        rotation_deg=angle,
        text_style_id="wide",
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    from mycad.ui.geometric_tolerance_layout import FrameLayout

    frame_layout = cast(
        "Callable[[FeatureControlFrame], FrameLayout]", _private_member(tools, "_layout")
    )
    layout = frame_layout(frame)
    glyph_snapshot = tools.graphic_frame_export_glyphs((frame,))
    preview = prepare_dxf_output_preview(
        services.kernel,
        tolerance_graphics=True,
        graphic_frame_widths=tools.graphic_frame_export_widths((frame,)),
        graphic_frame_glyphs=glyph_snapshot,
    )
    path = tmp_path / "cells.dxf"
    preview.write(path)
    readfile = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    space = readfile(path).modelspace()
    lines = list(space.query("LINE"))
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def world(x: float, y: float) -> tuple[float, float]:
        return (20 + cosine * x + sine * y, 30 + sine * x - cosine * y)

    hatches = list(space.query("HATCH"))
    assert len(hatches) == len(glyph_snapshot[frame.frame_id])
    for hatch, contours in zip(hatches, glyph_snapshot[frame.frame_id], strict=True):
        assert len(hatch.paths) == len(contours)
        for boundary, contour in zip(hatch.paths, contours, strict=True):
            assert tuple(boundary.vertices[0])[:2] == pytest.approx(world(*contour[0]))
    modifier_cell = layout.rows[0].cells[1]
    expected_center = world(
        modifier_cell.bounds.right() - 2.25 * layout.scale,
        modifier_cell.bounds.center().y(),
    )
    assert any(
        circle.dxf.radius == pytest.approx(1.45 * layout.scale)
        and tuple(circle.dxf.center)[:2] == pytest.approx(expected_center)
        for circle in space.query("CIRCLE")
    )

    for row in layout.rows:
        for cell in row.cells:
            rect = cell.bounds
            a, b = world(rect.right(), rect.top()), world(rect.right(), rect.bottom())
            assert any(
                (
                    tuple(line.dxf.start)[:2] == pytest.approx(a)
                    and tuple(line.dxf.end)[:2] == pytest.approx(b)
                )
                or (
                    tuple(line.dxf.start)[:2] == pytest.approx(b)
                    and tuple(line.dxf.end)[:2] == pytest.approx(a)
                )
                for line in lines
            )
