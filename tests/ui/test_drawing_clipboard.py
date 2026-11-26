# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Copy and paste independent 2D drawing objects through the system clipboard."""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.drawing_clipboard import (
    decode_drawing_clipboard,
    encode_drawing_clipboard,
    instantiate_drawing_clipboard,
)
from mycad.ui.sketch_editor import SketchEditorDialog


@pytest.fixture(autouse=True)
def clear_test_clipboard(qapp: QApplication) -> Iterator[None]:
    yield
    qapp.clipboard().clear()


def test_clipboard_roundtrip_creates_new_ids_and_rebinds_constraints() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (3, 4), 2)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(5, 2),
    )
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle), (dimension,))
    decoded = decode_drawing_clipboard(encode_drawing_clipboard(source))
    assert decoded == source
    entities, constraints = instantiate_drawing_clipboard(decoded, (20, 30))
    copied_line, copied_circle = entities
    assert isinstance(copied_line, LineEntity) and isinstance(copied_circle, CircleEntity)
    assert copied_line.entity_id != line.entity_id and copied_line.start_mm == (20, 30)
    assert copied_circle.entity_id != circle.entity_id and copied_circle.center_mm == (23, 34)
    assert constraints[0].constraint_id != dimension.constraint_id
    assert constraints[0].references[0].entity_id == copied_line.entity_id
    assert constraints[0].position_mm == (25, 32)


def test_clipboard_style_matches_destination_or_detaches() -> None:
    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        precision=3,
        scale=2,
        style_name="加工图",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    matching = DimensionStyleTable((DimensionStyle("加工图", 3, 2),), "加工图")
    different = DimensionStyleTable((DimensionStyle("加工图", 2, 1),), "加工图")
    assert (
        instantiate_drawing_clipboard(sketch, (0, 0), styles=matching)[1][0].style_name == "加工图"
    )
    detached = instantiate_drawing_clipboard(sketch, (0, 0), styles=different)[1][0]
    assert detached.style_name is None and (detached.precision, detached.scale) == (3, 2)
    assert instantiate_drawing_clipboard(sketch, (0, 0))[1][0].style_name is None


def test_ordinate_dimension_value_is_relative_to_both_copied_points() -> None:
    line = LineEntity(uuid4().hex, (1, 2), (11, 2))
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        10,
        "mm",
        axis="ordinate_x",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    _entities, constraints = instantiate_drawing_clipboard(sketch, (20, 30))
    assert constraints[0].value == 10


def test_clipboard_roundtrips_all_supported_entity_kinds() -> None:
    from mycad.core.sketch import (
        ArcEntity,
        PointEntity,
        PolylineEntity,
        RectangleEntity,
        SplineEntity,
    )

    entities = (
        PointEntity(uuid4().hex, (1, 1)),
        LineEntity(uuid4().hex, (0, 0), (10, 0)),
        CircleEntity(uuid4().hex, (2, 3), 2),
        ArcEntity(uuid4().hex, (0, 0), 5, 10, 120),
        RectangleEntity(uuid4().hex, (0, 0), (4, 3)),
        PolylineEntity(uuid4().hex, ((0, 0), (4, 0), (4, 5)), bulges=(0.5, 0)),
        SplineEntity(uuid4().hex, ((0, 0), (1, 1), (2, 1), (3, 0))),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    decoded = decode_drawing_clipboard(encode_drawing_clipboard(sketch))
    clones, _constraints = instantiate_drawing_clipboard(decoded, (10, 20))
    assert tuple(type(entity) for entity in clones) == tuple(type(entity) for entity in entities)
    assert all(old.entity_id != new.entity_id for old, new in zip(entities, clones, strict=True))
    assert isinstance(clones[5], PolylineEntity) and clones[5].bulges == (0.5, 0)


def test_clipboard_rejects_huge_integer_without_changing_draft(qtbot: QtBot) -> None:
    from PySide6.QtCore import QByteArray, QMimeData

    from mycad.ui.drawing_clipboard import DRAWING_CLIPBOARD_MIME

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert editor.canvas.replace_draft_entities((line,))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    envelope = json.loads(encode_drawing_clipboard(sketch))
    envelope["sketch"]["entities"][0]["start_mm"][0] = 10**400
    mime = QMimeData()
    mime.setData(DRAWING_CLIPBOARD_MIME, QByteArray(json.dumps(envelope).encode()))
    QApplication.clipboard().setMimeData(mime)

    assert not editor.canvas.begin_clipboard_paste()
    assert "无效" in editor.canvas.message
    assert editor.canvas.entities == [line]
    assert not editor.canvas.clipboard_paste_active


def test_clipboard_unrepresentable_preview_preserves_draft(qtbot: QtBot) -> None:
    from PySide6.QtCore import QByteArray, QMimeData

    from mycad.core.sketch import PointEntity
    from mycad.ui.drawing_clipboard import DRAWING_CLIPBOARD_MIME

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    existing = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert editor.canvas.replace_draft_entities((existing,))
    sketch = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (PointEntity(uuid4().hex, (-1e308, 0)), PointEntity(uuid4().hex, (1e308, 0))),
    )
    mime = QMimeData()
    mime.setData(DRAWING_CLIPBOARD_MIME, QByteArray(encode_drawing_clipboard(sketch)))
    QApplication.clipboard().setMimeData(mime)
    assert editor.canvas.begin_clipboard_paste()
    with qtbot.capture_exceptions() as exceptions:
        QTest.mouseMove(editor.canvas, editor.canvas.rect().center())
        editor.canvas.grab()
    assert not exceptions
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    assert editor.canvas.entities == [existing]
    assert editor.canvas.clipboard_paste_active
    assert "粘贴位置无效" in editor.canvas.message
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert not editor.canvas.clipboard_paste_active and editor.canvas.entities == [existing]


@pytest.mark.parametrize("mixed", [False, True])
def test_legacy_clipboard_pastes_ellipse_from_center(qtbot: QtBot, mixed: bool) -> None:
    from PySide6.QtCore import QByteArray, QMimeData
    from PySide6.QtGui import QImage

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.sketch import EllipseEntity
    from mycad.ui.drawing_clipboard import (
        DRAWING_CLIPBOARD_MIME,
        DRAWING_MIXED_CLIPBOARD_MIME,
        encode_mixed_clipboard,
        raster_from_clipboard_image,
    )

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    ellipse = EllipseEntity(uuid4().hex, (2, 3), 4, 2)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (ellipse,))
    mime = QMimeData()
    pasted: list[tuple[Sketch, tuple[DrawingRaster, ...]]] = []
    if mixed:
        image = QImage(2, 2, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.red)
        raster = raster_from_clipboard_image(image, "0", None)
        mime.setData(
            DRAWING_MIXED_CLIPBOARD_MIME, QByteArray(encode_mixed_clipboard(sketch, (raster,)))
        )
        editor.canvas.commit_mixed_clipboard = lambda data, images, _styles, _fonts: pasted.append(
            (data, images)
        )
    else:
        mime.setData(DRAWING_CLIPBOARD_MIME, QByteArray(encode_drawing_clipboard(sketch)))
    QApplication.clipboard().setMimeData(mime)
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((10, 11), exact_point=True)
    if mixed:
        assert len(pasted) == 1
        result = pasted[0][0].entities[0]
        assert pasted[0][1][0].origin_mm == pytest.approx((8, 8))
    else:
        assert len(editor.canvas.entities) == 1
        result = editor.canvas.entities[0]
    assert isinstance(result, EllipseEntity) and result.center_mm == pytest.approx((10, 11))
    assert result.entity_id != ellipse.entity_id


def test_clipboard_rejects_invalid_geometry_reference() -> None:
    from mycad.core.sketch import PolylineEntity

    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    bad = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(polyline.entity_id, "segment", 9),),
        10,
        "mm",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,), (bad,))
    with pytest.raises(ValueError):
        decode_drawing_clipboard(encode_drawing_clipboard(sketch))


@pytest.mark.parametrize("data", [b"", b"{}", b"not json", b"x" * 1000001])
def test_clipboard_rejects_invalid_or_oversized_data(data: bytes) -> None:
    with pytest.raises(ValueError):
        decode_drawing_clipboard(data)


def test_canvas_copy_paste_shortcuts_and_undo(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.setFocus()
    QTest.keyClick(editor.canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(editor.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((20, 30))
    )
    assert len(editor.canvas.entities) == 2
    pasted = editor.canvas.entities[1]
    assert isinstance(pasted, LineEntity) and pasted.entity_id != line.entity_id
    assert pasted.start_mm == pytest.approx((20, 30), abs=0.2)
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [line]


def test_clipboard_crosses_drawing_editors_and_cancel_is_safe(qtbot: QtBot) -> None:
    source = SketchEditorDialog(select_committed_entities=True)
    target = SketchEditorDialog(select_committed_entities=True)
    for editor in (source, target):
        qtbot.addWidget(editor)
        editor.resize(1100, 800)
        editor.show()
    circle = CircleEntity(uuid4().hex, (3, 4), 2)
    assert source.canvas.replace_draft_entities((circle,))
    source.canvas.selected_entity_ids = {circle.entity_id}
    assert source.canvas.copy_to_clipboard()
    assert target.canvas.begin_clipboard_paste()
    QTest.keyClick(target.canvas, Qt.Key.Key_Escape)
    assert not target.canvas.entities
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((8, 9))
    )
    copied = target.canvas.entities[0]
    assert isinstance(copied, CircleEntity) and copied.center_mm == pytest.approx((8, 9), abs=0.2)
    assert copied.entity_id != circle.entity_id


def test_main_edit_menu_copies_and_pastes_selected_drawing(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=()))
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    window.menu_edit.aboutToShow.emit()
    assert window.act_copy.isEnabled()
    window.act_copy.trigger()
    window.menu_edit.aboutToShow.emit()
    assert window.act_paste.isEnabled()
    window.act_paste.trigger()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((20, 20))
    )
    assert len(editor.canvas.entities) == 2


def test_saved_geometry_copies_to_another_drawing_and_reopens(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    source, unit = window.active_sketch_dialog(), window.execution_unit
    assert source is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert source.canvas.replace_draft_entities((line,))
    source.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not source and not unit.is_busy, timeout=10000
    )
    source = window.active_sketch_dialog()
    assert source is not None
    source.canvas.selected_entity_ids = {line.entity_id}
    assert source.canvas.copy_to_clipboard()
    window.act_new_drawing.trigger()
    target, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert target is not None and loaded is not None and target is not source
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((20, 20))
    )
    pasted = target.canvas.entities[0]
    assert isinstance(pasted, LineEntity) and pasted.entity_id != line.entity_id
    window.request_undo()
    assert not target.canvas.entities
    window.request_redo()
    assert target.canvas.entities == [pasted]
    target.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not target and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "clipboard.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == (pasted,)


def test_cross_drawing_paste_imports_layer_and_reopens(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow
    from mycad.ui.viewport import GLViewport

    monkeypatch.setattr(GLViewport, "paintGL", lambda *_args, **_kwargs: None)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    source, unit = window.active_sketch_dialog(), window.execution_unit
    assert source is not None and unit is not None
    source.request_layer_update(source.layer_table.add(SketchLayer("PARTS")), ".")
    qtbot.waitUntil(
        lambda current=source: not unit.is_busy and len(current.layer_table.layers) > 1,
        timeout=10000,
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="PARTS")
    assert source.canvas.replace_draft_entities((line,))
    source.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not source and not unit.is_busy, timeout=10000
    )
    source = window.active_sketch_dialog()
    assert source is not None
    source.canvas.selected_entity_ids = {line.entity_id}
    assert source.canvas.copy_to_clipboard()
    window.act_new_drawing.trigger()
    target, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert target is not None and loaded is not None
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((20, 20))
    )
    assert target.canvas.entities and services.kernel.drawing_layers.get("PARTS").name == "PARTS"
    copied = target.canvas.entities[0]
    assert copied.layer_name == "PARTS"
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert not target.canvas.entities
    with pytest.raises(KeyError):
        services.kernel.drawing_layers.get("PARTS")
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert services.kernel.drawing_layers.get("PARTS").name == "PARTS"
    assert target.canvas.entities == [copied]
    target.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not target and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "clipboard-layer.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == (copied,)
    assert reopened_services.kernel.drawing_layers.get("PARTS").name == "PARTS"


def test_failed_paste_after_layer_import_restores_document(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    source = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(source)
    source.canvas.set_layer_table(source.canvas.layer_table.add(SketchLayer("PARTS")), "0")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="PARTS")
    assert source.canvas.replace_draft_entities((line,))
    source.canvas.selected_entity_ids = {line.entity_id}
    assert source.canvas.copy_to_clipboard()
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    target, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert target is not None and loaded is not None
    previous_layers = services.kernel.drawing_layers.add(SketchLayer("PREVIOUS"))
    loaded.bus.execute(
        "drawing.layers.set",
        {
            "layers": previous_layers.to_mapping(),
            "dimension_layer": services.kernel.dimension_layer,
            "assignments": [],
        },
        "local",
    )
    loaded.bus.undo()
    draft = LineEntity(uuid4().hex, (1, 1), (5, 1))
    assert target.canvas.replace_draft_entities((draft,))
    assert target.canvas.undo_last_operation()
    commands = tuple(loaded.document.commands)
    assert target.canvas.begin_clipboard_paste()

    def reject(*args: object, **kwargs: object) -> bool:
        return False

    with monkeypatch.context() as patch:
        patch.setattr(target.canvas, "replace_draft_entities", reject)
        target.canvas.add_coordinate_point((20, 20), exact_point=True)
    assert tuple(loaded.document.commands) == commands
    with pytest.raises(KeyError):
        services.kernel.drawing_layers.get("PARTS")
    assert not target.canvas.entities and target.canvas.clipboard_paste_active
    assert "粘贴未完成" in target.canvas.message
    QTest.keyClick(target.canvas, Qt.Key.Key_Escape)
    assert target.canvas.redo_last_operation() and target.canvas.entities == [draft]
    assert target.canvas.undo_last_operation()
    loaded.bus.redo()
    assert services.kernel.drawing_layers.get("PREVIOUS").name == "PREVIOUS"
    loaded.bus.undo()
    assert target.canvas.begin_clipboard_paste()
    target.canvas.add_coordinate_point((20, 20), exact_point=True)
    assert len(target.canvas.entities) == 1
    assert services.kernel.drawing_layers.get("PARTS").name == "PARTS"


@pytest.mark.parametrize("layer_history", ["draft", "undo", "redo", "failure"])
def test_paste_layer_import_keeps_existing_mixed_fillet_committable(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layer_history: str
) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    source = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(source)
    source.canvas.set_layer_table(source.canvas.layer_table.add(SketchLayer("PARTS")), "0")
    copy = LineEntity(uuid4().hex, (30, 0), (35, 0), layer_name="PARTS")
    assert source.canvas.replace_draft_entities((copy,))
    source.canvas.selected_entity_ids = {copy.entity_id}
    assert source.canvas.copy_to_clipboard()
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second)),
        session_identity=0,
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=10000)
    mixed_before = canvas.mixed_move
    saved = services.kernel.sketches
    changed = replace(saved[0], entities=(replace(first, end_mm=(11, 0)), second))
    assert not canvas.rebase_mixed_layers((changed,), canvas.layer_table)
    assert canvas.mixed_move == mixed_before
    relations = tuple(canvas.pending_cross_tangencies)
    assert len(relations) == 2
    assert canvas.begin_clipboard_paste()
    if layer_history == "failure":

        def reject(*args: object, **kwargs: object) -> bool:
            return False

        with monkeypatch.context() as patch:
            patch.setattr(canvas, "replace_draft_entities", reject)
            canvas.add_coordinate_point((30, 10), exact_point=True)
        assert canvas.clipboard_paste_active
        assert tuple(canvas.pending_cross_tangencies) == relations
        with pytest.raises(KeyError):
            services.kernel.drawing_layers.get("PARTS")
    canvas.add_coordinate_point((30, 10), exact_point=True)
    assert canvas.mixed_move is not None
    assert canvas.mixed_move.source_revision == loaded.document.revision
    if layer_history in ("undo", "redo"):
        window.request_undo()
        window.request_undo()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        with pytest.raises(KeyError):
            services.kernel.drawing_layers.get("PARTS")
        if layer_history == "redo":
            window.request_redo()
            qtbot.waitUntil(
                lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000
            )
            assert services.kernel.drawing_layers.get("PARTS").name == "PARTS"
            window.request_redo()
    else:
        assert canvas.undo_last_operation()
        assert canvas.redo_last_operation()
    assert tuple(canvas.pending_cross_tangencies) == relations
    editor.finish_sketch()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert window.active_sketch_dialog() is not editor, editor.status_label.text()
    result = services.kernel.sketches
    saved_relations = services.kernel.cross_sketch_tangencies
    assert len(saved_relations) == 2
    assert any(entity.layer_name == "PARTS" for sketch in result for entity in sketch.entities) == (
        layer_history != "undo"
    )
    loaded.bus.undo()
    loaded.bus.redo()
    assert services.kernel.sketches == result
    assert services.kernel.cross_sketch_tangencies == saved_relations
    path = tmp_path / "mixed-fillet-paste.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == result
    assert reopened_services.kernel.cross_sketch_tangencies == saved_relations


def test_text_editor_shortcuts_keep_normal_text_clipboard(qtbot: QtBot) -> None:

    from mycad import app
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=()))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    field = editor.drawing_command_bar.input
    field.setText("hello")
    field.selectAll()
    field.setFocus()
    QTest.keyClick(field, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    field.clear()
    QTest.keyClick(field, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert field.text() == "hello"


def test_paste_preserves_internal_dimension_and_supports_coordinate_input(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(5, 2),
    )
    assert editor.canvas.replace_draft_entities((line,), new_relations=(dimension,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    editor.drawing_command_bar.input.setText("20,30")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 2
    copied = editor.canvas.entities[-1]
    assert isinstance(copied, LineEntity) and copied.start_mm == (20, 30)
    assert len(editor.canvas.constraints) == 2
    copied_dimension = editor.canvas.constraints[-1]
    assert copied_dimension.references[0].entity_id == copied.entity_id
    assert copied_dimension.position_mm == (25, 32)
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [line] and editor.canvas.constraints == [dimension]


def test_copyclip_and_pasteclip_commands(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    for value in ("COPYCLIP", "PASTECLIP", "20,30"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 2
    copied = editor.canvas.entities[-1]
    assert isinstance(copied, LineEntity) and copied.start_mm == (20, 30)


def test_paste_imports_missing_target_layer_and_undoes(qtbot: QtBot) -> None:
    from mycad.core.sketch_layers import SketchLayer

    source = SketchEditorDialog(select_committed_entities=True)
    target = SketchEditorDialog(select_committed_entities=True)
    for editor in (source, target):
        qtbot.addWidget(editor)
        editor.show()
    layers = source.canvas.layer_table.add(SketchLayer("PARTS"))
    source.canvas.set_layer_table(layers, "0")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="PARTS")
    assert source.canvas.replace_draft_entities((line,))
    source.canvas.selected_entity_ids = {line.entity_id}
    assert source.canvas.copy_to_clipboard()
    assert target.canvas.begin_clipboard_paste()
    QTest.keyClick(target.canvas, Qt.Key.Key_Escape)
    with pytest.raises(KeyError):
        target.canvas.layer_table.get("PARTS")
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((20, 20))
    )
    assert target.canvas.layer_table.get("PARTS").name == "PARTS"
    assert target.canvas.entities[0].layer_name == "PARTS"
    assert target.canvas.undo_last_operation()
    assert not target.canvas.entities
    with pytest.raises(KeyError):
        target.canvas.layer_table.get("PARTS")


def test_layer_import_failure_preserves_paste_for_retry(qtbot: QtBot) -> None:
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    source = SketchEditorDialog(select_committed_entities=True)
    target = SketchEditorDialog(select_committed_entities=True)
    for editor in (source, target):
        qtbot.addWidget(editor)
        editor.show()
    source.canvas.set_layer_table(source.canvas.layer_table.add(SketchLayer("PARTS")), "0")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="PARTS")
    assert source.canvas.replace_draft_entities((line,))
    source.canvas.selected_entity_ids = {line.entity_id}
    assert source.canvas.copy_to_clipboard()
    target.canvas.preserve_document_layers = True

    def fail(_layers: SketchLayerTable, _styles: object, _fonts: object) -> Callable[[bool], None]:
        raise ValueError("图层导入失败")

    target.canvas.import_clipboard_layers = fail
    assert target.canvas.begin_clipboard_paste()
    QTest.mouseClick(
        target.canvas, Qt.MouseButton.LeftButton, pos=target.canvas.local_to_screen((20, 20))
    )
    assert target.canvas.clipboard_paste_active and not target.canvas.entities
    assert "图层导入失败" in target.canvas.message
    with pytest.raises(KeyError):
        target.canvas.layer_table.get("PARTS")


def test_copy_dimension_requires_its_selected_geometry(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
    )
    assert editor.canvas.replace_draft_entities((line,), new_relations=(dimension,))
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    assert not editor.canvas.copy_to_clipboard()
    assert "引用" in editor.canvas.message


def test_copy_reports_relations_outside_selection(qtbot: QtBot) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (10, 0), (10, 10))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(line.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    assert editor.canvas.replace_draft_entities((line, second), new_relations=(relation,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    cross = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(uuid4().hex, line.entity_id),
        CrossSketchRef(uuid4().hex, uuid4().hex),
        "line_left",
    )
    editor.canvas.associative_tangencies_provider = lambda: (cross,)
    assert editor.canvas.copy_to_clipboard()
    assert "关联未复制" in editor.canvas.message
    assert "未选图元的约束" in editor.canvas.message and "对象相切" in editor.canvas.message


def test_copy_reports_array_replacement_source(qtbot: QtBot) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    replacement = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((replacement,))
    editor.canvas.selected_entity_ids = {replacement.entity_id}
    sketch_id = uuid4().hex
    source = ArrayEntityRef(sketch_id, uuid4().hex)
    target = ArrayEntityRef(sketch_id, uuid4().hex)
    replacement_ref = ArrayEntityRef(sketch_id, replacement.entity_id)
    member = ArrayMember(source, target, 0, 1, replacement=ArrayReplacement(replacement_ref))
    array = AssociativeRectArray(uuid4().hex, WorkPlaneFrame.xy(), 1, 2, 0, 5, (source,), (member,))
    editor.canvas.associative_arrays_provider = lambda: (array,)
    assert editor.canvas.copy_to_clipboard()
    assert "阵列关联" in editor.canvas.message and "未复制" in editor.canvas.message


def test_canvas_context_menu_copies_and_pastes(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QMenu

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    for option in ("复制", "粘贴"):

        def choose(label: str = option) -> None:
            menu = QApplication.activePopupWidget()
            if isinstance(menu, QMenu):
                action = next(
                    (item for item in menu.actions() if item.text().startswith(label)), None
                )
                if action is not None:
                    QTest.mouseClick(
                        menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center()
                    )
                else:
                    menu.close()

        QTimer.singleShot(0, choose)
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(20, 20), QPoint(20, 20))
        editor.canvas.contextMenuEvent(event)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((20, 20))
    )
    assert len(editor.canvas.entities) == 2


def test_right_click_cancel_paste_consumes_context_event(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QMenu

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    QTest.mouseClick(editor.canvas, Qt.MouseButton.RightButton)
    assert not editor.canvas.clipboard_paste_active
    popup_seen: list[bool] = []

    def close_unexpected_popup() -> None:
        popup = QApplication.activePopupWidget()
        if isinstance(popup, QMenu):
            popup_seen.append(True)
            popup.close()

    QTimer.singleShot(0, close_unexpected_popup)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(20, 20), QPoint(20, 20))
    editor.canvas.contextMenuEvent(event)
    QApplication.processEvents()
    assert not popup_seen
    assert editor.canvas.entities == [line]
