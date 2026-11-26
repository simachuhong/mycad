# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimension styles retain their complete appearance on cross-drawing paste."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QApplication

from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.drawing_clipboard import (
    decode_drawing_clipboard_data,
    decode_drawing_clipboard_full,
    decode_mixed_clipboard_data,
    encode_drawing_clipboard,
    encode_mixed_clipboard,
    reconcile_clipboard_styles,
)


@pytest.fixture(autouse=True)
def clear_clipboard(qapp: QApplication):
    yield
    qapp.clipboard().clear()


def test_clipboard_retains_full_style_and_resolves_name_conflicts() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name="加工图",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    source = DimensionStyle("加工图", arrow_first="filled", center_mark="line")
    source_table = DimensionStyleTable((source,), source.name)
    decoded, carried = decode_drawing_clipboard_data(encode_drawing_clipboard(sketch, source_table))
    assert decoded == sketch and carried == source_table

    destination = DimensionStyleTable((DimensionStyle("加工图"),), "加工图")
    merged, renamed = reconcile_clipboard_styles(decoded, carried, destination)
    copied = merged.get(renamed.constraints[0].style_name or "")
    assert copied.name != source.name
    assert copied.arrow_first == "filled" and copied.center_mark == "line"
    assert merged.current_name == destination.current_name
    assert merged.get("加工图") == destination.current
    again, repeated = reconcile_clipboard_styles(decoded, carried, merged)
    assert again == merged and repeated.constraints[0].style_name == copied.name


def test_clipboard_carries_dimension_font_style() -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name="检验",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    styles = DimensionStyleTable((DimensionStyle("检验", text_style_id="font"),), "检验")
    fonts = TextStyleTable((TextStyle("font", "字体", "Font A"),), "font")
    with pytest.raises(ValueError):
        encode_drawing_clipboard(sketch, styles)
    decoded, decoded_styles, decoded_fonts = decode_drawing_clipboard_full(
        encode_drawing_clipboard(sketch, styles, fonts)
    )
    assert (decoded, decoded_styles, decoded_fonts) == (sketch, styles, fonts)


def test_dxf_import_reconciles_dimension_font_and_undoes(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name="检验",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    styles = DimensionStyleTable((DimensionStyle("检验", text_style_id="font"),), "检验")
    fonts = TextStyleTable((TextStyle("font", "字体", "Font A"),), "font")
    path = tmp_path / "font.dxf"
    write_sketches_dxf((sketch,), path, dimension_styles=styles, text_styles=fonts)
    incoming = read_sketch_dxf(path).text_styles
    assert incoming is not None
    collision = incoming.current.style_id
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    target_fonts = TextStyleTable((TextStyle(), TextStyle(collision, "字体", "Font B")))
    loaded.bus.execute("drawing.text_styles.set", target_fonts.to_mapping(), "local")

    def yes(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(lambda: bool(services.kernel.sketches) and not unit.is_busy, timeout=15000)
    imported = services.kernel.sketches[0].constraints[0]
    assert imported.style_name is not None
    font_id = services.kernel.drawing_dimension_styles.get(imported.style_name).text_style_id
    assert font_id is not None and font_id != collision
    assert services.kernel.drawing_text_styles.get(font_id).font_family == "Font A"
    assert services.kernel.drawing_text_styles.get(collision).font_family == "Font B"
    window.request_undo()
    qtbot.waitUntil(lambda: not services.kernel.sketches and not unit.is_busy, timeout=15000)
    assert services.kernel.drawing_text_styles == target_fonts


@pytest.mark.parametrize("mixed", (False, True))
def test_paste_dimension_font_style_handles_conflicts_and_undo(qtbot: object, mixed: bool) -> None:
    from PySide6.QtCore import QByteArray, QMimeData
    from PySide6.QtGui import QImage
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.ui.drawing_clipboard import (
        DRAWING_CLIPBOARD_MIME,
        DRAWING_MIXED_CLIPBOARD_MIME,
        raster_from_clipboard_image,
    )
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    target_fonts = TextStyleTable((TextStyle(), TextStyle("font", "字体", "Font B")))
    loaded.bus.execute("drawing.text_styles.set", target_fonts.to_mapping(), "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name="检验",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    styles = DimensionStyleTable((DimensionStyle("检验", text_style_id="font"),), "检验")
    fonts = TextStyleTable((TextStyle("font", "字体", "Font A"),), "font")
    mime = QMimeData()
    if mixed:
        image = raster_from_clipboard_image(QImage(1, 1, QImage.Format.Format_RGB32), "0")
        mime.setData(
            DRAWING_MIXED_CLIPBOARD_MIME,
            QByteArray(encode_mixed_clipboard(sketch, (image,), styles, fonts)),
        )
    else:
        mime.setData(
            DRAWING_CLIPBOARD_MIME, QByteArray(encode_drawing_clipboard(sketch, styles, fonts))
        )
    QApplication.clipboard().setMimeData(mime)
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((20, 20), exact_point=True)
    assert not editor.canvas.clipboard_paste_active, editor.status_label.text()
    imported = services.kernel.drawing_dimension_styles.get("检验").text_style_id
    assert imported is not None and imported != "font"
    assert services.kernel.drawing_text_styles.get(imported).font_family == "Font A"
    assert services.kernel.drawing_text_styles.get("font").font_family == "Font B"
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_text_styles == target_fonts, timeout=10000)
    assert window.execution_unit is not None
    qtbot.waitUntil(lambda: not window.execution_unit.is_busy, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(lambda: len(services.kernel.drawing_text_styles.styles) == 3, timeout=10000)


def test_mixed_clipboard_retains_styles() -> None:
    from PySide6.QtGui import QImage

    from mycad.ui.drawing_clipboard import raster_from_clipboard_image

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name="样式",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    style = DimensionStyle("样式", center_mark="line")
    table = DimensionStyleTable((style,), style.name)
    image = raster_from_clipboard_image(QImage(1, 1, QImage.Format.Format_RGB32), "0")
    decoded, images, carried = decode_mixed_clipboard_data(
        encode_mixed_clipboard(sketch, (image,), table)
    )
    assert decoded == sketch and images == (image,) and carried == table


def test_mixed_paste_imports_conflicting_style_and_undoes(qtbot: object) -> None:
    from PySide6.QtCore import QByteArray, QMimeData
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.drawing_clipboard import DRAWING_MIXED_CLIPBOARD_MIME, raster_from_clipboard_image
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    original = services.kernel.drawing_dimension_styles
    source_style = DimensionStyle(original.current_name, arrow_first="filled", center_mark="line")
    source = DimensionStyleTable((source_style,), source_style.name)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name=source_style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    image = raster_from_clipboard_image(QImage(1, 1, QImage.Format.Format_RGB32), "0")
    mime = QMimeData()
    mime.setData(
        DRAWING_MIXED_CLIPBOARD_MIME, QByteArray(encode_mixed_clipboard(sketch, (image,), source))
    )
    QApplication.clipboard().setMimeData(mime)
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((20, 20), exact_point=True)
    copied = services.kernel.sketches[0].constraints[0]
    copied_style = services.kernel.drawing_dimension_styles.get(copied.style_name or "")
    assert copied_style.name != source_style.name and copied_style.arrow_first == "filled"
    unit = window.execution_unit
    assert unit is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not services.kernel.sketches and not services.kernel.drawing_rasters
    assert services.kernel.drawing_dimension_styles == original
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(services.kernel.sketches) == 1 and len(services.kernel.drawing_rasters) == 1
    assert services.kernel.drawing_dimension_styles.get(copied_style.name) == copied_style


def test_plain_paste_imports_style_and_undoes_as_one(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QByteArray, QMimeData
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.drawing_clipboard import DRAWING_CLIPBOARD_MIME
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    original = services.kernel.drawing_dimension_styles
    style = DimensionStyle(original.current_name, arrow_first="filled")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    mime = QMimeData()
    mime.setData(
        DRAWING_CLIPBOARD_MIME,
        QByteArray(encode_drawing_clipboard(sketch, DimensionStyleTable((style,), style.name))),
    )
    QApplication.clipboard().setMimeData(mime)
    assert editor.canvas.begin_clipboard_paste()
    with monkeypatch.context() as patch:
        patch.setattr(editor.canvas, "replace_draft_entities", lambda *_args, **_kwargs: False)
        editor.canvas.add_coordinate_point((20, 20), exact_point=True)
    assert editor.canvas.clipboard_paste_active and not editor.canvas.entities
    assert services.kernel.drawing_dimension_styles == original
    assert not window.loaded_document().document.commands
    editor.canvas.add_coordinate_point((20, 20), exact_point=True)
    assert len(editor.canvas.entities) == 1 and len(editor.canvas.constraints) == 1
    copied = editor.canvas.constraints[0]
    copied_style = services.kernel.drawing_dimension_styles.get(copied.style_name or "")
    assert copied_style.name != style.name and copied_style.arrow_first == "filled"
    unit = window.execution_unit
    assert unit is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not editor.canvas.entities and not editor.canvas.constraints
    assert services.kernel.drawing_dimension_styles == original
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(editor.canvas.entities) == 1 and len(editor.canvas.constraints) == 1
    assert services.kernel.drawing_dimension_styles.get(copied_style.name) == copied_style


def test_copy_source_style_to_another_drawing_and_reopen(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow
    from mycad.ui.viewport import GLViewport

    assert isinstance(qtbot, QtBot)
    monkeypatch.setattr(GLViewport, "paintGL", lambda *_args, **_kwargs: None)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    source, loaded = window.active_sketch_dialog(), window.loaded_document()
    unit = window.execution_unit
    assert source is not None and loaded is not None and unit is not None
    style = DimensionStyle("标准", arrow_first="filled", center_mark="line", center_size=4)
    loaded.bus.execute(
        "drawing.dimension_styles.set",
        DimensionStyleTable((style,), style.name).to_mapping(),
        "local",
    )
    window._sync_drawing_layers()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name=style.name,
    )
    assert source.canvas.replace_draft_entities((line,), new_relations=(dimension,))
    source.canvas.selected_entity_ids = {line.entity_id}
    source.canvas.selected_constraint_ids = {dimension.constraint_id}
    assert source.canvas.copy_to_clipboard()
    window.act_new_drawing.trigger()
    target, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert target is not None and loaded is not None and target is not source
    assert target.canvas.begin_clipboard_paste()
    target.canvas.add_coordinate_point((20, 20), exact_point=True)
    copied = target.canvas.constraints[0]
    copied_style = services.kernel.drawing_dimension_styles.get(copied.style_name or "")
    assert copied_style.name != style.name and copied_style.arrow_first == "filled"
    assert copied_style.center_mark == "line" and copied_style.center_size == 4
    target.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not target and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "copied-style.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    constraint = reopened.kernel.sketches[0].constraints[0]
    assert reopened.kernel.drawing_dimension_styles.get(constraint.style_name or "") == copied_style


@pytest.mark.parametrize("conflict", (False, True))
def test_dxf_import_recovers_style_as_one_undoable_operation(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conflict: bool
) -> None:
    from PySide6.QtWidgets import QMessageBox
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.formats.providers.dxf_provider import write_sketches_dxf
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    style = (
        DimensionStyle(
            "标准",
            arrow_first="filled",
            center_mark="line",
            dimension_color=1,
            extension_color=3,
            text_color=5,
            dimension_lineweight=35,
            extension_lineweight=70,
            dimension_linetype="DASHED",
            extension_linetype_first="DOTTED",
            extension_linetype_second="DASHDOT",
            suppress_extension_first=True,
            suppress_dimension_first=True,
        )
        if conflict
        else DimensionStyle("标准")
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name=style.name,
    )
    source = tmp_path / "style.dxf"
    write_sketches_dxf(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,)),),
        source,
        dimension_styles=DimensionStyleTable((style,), style.name),
    )
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert loaded is not None and unit is not None
    original = services.kernel.drawing_dimension_styles
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes
    )
    window._queue_dxf_sketch_import(source, unit_override=None)
    qtbot.waitUntil(
        lambda: (
            len(loaded.document.commands) == 1
            and not unit.is_busy
            and not unit.is_delivering_result
        ),
        timeout=10000,
    )
    restored = services.kernel.sketches[0].constraints[0]
    restored_style = services.kernel.drawing_dimension_styles.get(restored.style_name or "")
    assert (restored_style.name != style.name) is conflict
    assert restored_style == replace(style, name=restored_style.name)
    loaded.bus.undo()
    assert not services.kernel.sketches and services.kernel.drawing_dimension_styles == original
    loaded.bus.redo()
    path = tmp_path / "imported.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_dimension_styles.get(restored.style_name or "") == restored_style


def test_cancel_dxf_style_import_keeps_document_unchanged(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.formats.providers.dxf_provider import write_sketches_dxf
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    style = DimensionStyle("源样式", arrow_first="filled")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name=style.name,
    )
    path = tmp_path / "cancel.dxf"
    write_sketches_dxf(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,)),),
        path,
        dimension_styles=DimensionStyleTable((style,), style.name),
    )
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert loaded is not None and unit is not None
    original = services.kernel.drawing_dimension_styles
    seen: list[str] = []

    def decline(
        _parent: object, _title: str, text: str, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        seen.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", decline)
    window._queue_dxf_sketch_import(path, unit_override=None)
    qtbot.waitUntil(
        lambda: bool(seen) and not unit.is_busy and not unit.is_delivering_result, timeout=10000
    )
    assert not loaded.document.commands and not services.kernel.sketches
    assert services.kernel.drawing_dimension_styles == original


@pytest.mark.parametrize("mixed", (False, True))
def test_paste_style_into_v7_drawing_upgrades_and_undoes(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mixed: bool
) -> None:
    from PySide6.QtCore import QByteArray, QMimeData
    from PySide6.QtGui import QImage
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.core.document import Document
    from mycad.core.persistence import save_document
    from mycad.ui.drawing_clipboard import (
        DRAWING_CLIPBOARD_MIME,
        DRAWING_MIXED_CLIPBOARD_MIME,
        raster_from_clipboard_image,
    )
    from mycad.ui.main_window import MainWindow
    from mycad.ui.viewport import GLViewport

    assert isinstance(qtbot, QtBot)
    monkeypatch.setattr(GLViewport, "paintGL", lambda *_args, **_kwargs: None)
    services = app.build_app(discoverers=())
    path = tmp_path / "legacy.my2d"
    save_document(Document(services.registry, archive_version=7, document_type="drawing2d"), path)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.open_document_path(path)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not None and not unit.is_busy, timeout=10000
    )
    target, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert target is not None and loaded is not None and loaded.document.archive_version == 7
    active_services = window._services
    assert active_services is not None
    style = DimensionStyle(
        "源样式", arrow_first="filled", linear_tolerance=DimensionTolerance("symmetric", 0.1, -0.1)
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name=style.name,
        tolerance=DimensionTolerance("deviation", 0.2, -0.1),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    mime = QMimeData()
    table = DimensionStyleTable((style,), style.name)
    if mixed:
        image = raster_from_clipboard_image(QImage(1, 1, QImage.Format.Format_RGB32), "0")
        mime.setData(
            DRAWING_MIXED_CLIPBOARD_MIME,
            QByteArray(encode_mixed_clipboard(sketch, (image,), table)),
        )
    else:
        mime.setData(DRAWING_CLIPBOARD_MIME, QByteArray(encode_drawing_clipboard(sketch, table)))
    QApplication.clipboard().setMimeData(mime)
    assert target.canvas.begin_clipboard_paste()
    if not mixed:
        with monkeypatch.context() as patch:
            patch.setattr(target.canvas, "replace_draft_entities", lambda *_args, **_kwargs: False)
            target.canvas.add_coordinate_point((20, 20), exact_point=True)
        assert loaded.document.archive_version == 7 and not loaded.document.commands
        assert target.canvas.clipboard_paste_active
    target.canvas.add_coordinate_point((20, 20), exact_point=True)
    assert loaded.document.archive_version == 8
    assert len(active_services.kernel.sketches if mixed else target.canvas.entities) == 1
    assert active_services.kernel.drawing_dimension_styles.get("源样式") == style
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not (active_services.kernel.sketches if mixed else target.canvas.entities)
    with pytest.raises(KeyError):
        active_services.kernel.drawing_dimension_styles.get("源样式")
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(active_services.kernel.sketches if mixed else target.canvas.entities) == 1
    assert active_services.kernel.drawing_dimension_styles.get("源样式") == style


@pytest.mark.parametrize("source_saved", (False, True))
def test_copy_diameter_style_between_2d_drawings_undo_redo_and_reopen(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_saved: bool
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity
    from mycad.ui.main_window import MainWindow
    from mycad.ui.viewport import GLViewport

    assert isinstance(qtbot, QtBot)
    monkeypatch.setattr(GLViewport, "paintGL", lambda *_args, **_kwargs: None)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    source, loaded = window.active_sketch_dialog(), window.loaded_document()
    unit = window.execution_unit
    assert source is not None and loaded is not None and unit is not None
    style = DimensionStyle(
        "标准", arrow_first="open", arrow_second="closed", center_mark="mark", center_size=2
    )
    loaded.bus.execute(
        "drawing.dimension_styles.set",
        DimensionStyleTable((style,), style.name).to_mapping(),
        "local",
    )
    window._sync_drawing_layers()
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    dimension = SketchConstraint(
        uuid4().hex,
        "diameter",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    assert source.canvas.replace_draft_entities((circle,), new_relations=(dimension,))
    if source_saved:
        previous = source
        source.finish_sketch()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not previous and not unit.is_busy,
            timeout=10000,
        )
        source = window.active_sketch_dialog()
        assert source is not None
        assert any(
            entity.entity_id == circle.entity_id for entity, _ in source.canvas.background_entities
        )
    source.canvas.selected_entity_ids = {circle.entity_id}
    source.canvas.selected_constraint_ids = {dimension.constraint_id}
    assert source.canvas.copy_to_clipboard()
    window.act_new_drawing.trigger()
    target, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert target is not None and loaded is not None and target is not source
    assert target.canvas.begin_clipboard_paste()
    target.canvas.add_coordinate_point((20, 20), exact_point=True)
    copied = target.canvas.constraints[0]
    copied_style = services.kernel.drawing_dimension_styles.get(copied.style_name or "")
    assert copied_style == replace(style, name=copied_style.name)
    layout = target.canvas.dimension_layout(copied, target.canvas.dimension_entities())
    assert layout is not None and len(layout.arrows) == 2 and len(layout.extension_indices) == 2
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not target.canvas.entities and not target.canvas.constraints
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(target.canvas.entities) == len(target.canvas.constraints) == 1
    target.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not target and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "diameter-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    restored = reopened.kernel.sketches[0].constraints[0]
    assert reopened.kernel.drawing_dimension_styles.get(restored.style_name or "") == copied_style
