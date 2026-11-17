# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A pasted mixed sketch and its imported styles are one replayable operation."""

import base64
import struct
import zlib
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_mixed_create_imports_style_in_one_undo_and_replays(tmp_path: Path) -> None:
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
    image = DrawingRaster(uuid4().hex, base64.b64encode(png).decode(), (0, 0), 1, 1)
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    original = services.kernel.drawing_dimension_styles
    imported = DimensionStyle("复制样式", arrow_first="filled", center_mark="line")
    styles = DimensionStyleTable((*original.styles, imported), original.current_name)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        style_name=imported.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    params = sketch.to_state_mapping() | {
        "raster_batch": {"action": "add", "images": [image.to_mapping(version=2)]},
        "clipboard_styles": styles.to_mapping(),
    }
    conflicting = DimensionStyleTable(
        (DimensionStyle(original.current_name, arrow_first="tick"), imported), original.current_name
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "sketch.create",
            params | {"clipboard_styles": conflicting.to_mapping()},
            "local",
            version=44,
        )
    assert services.kernel.drawing_dimension_styles == original
    assert not services.kernel.sketches and not services.kernel.drawing_rasters
    loaded.bus.execute("sketch.create", params, "local", version=44)
    assert services.kernel.drawing_dimension_styles == styles
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (image,)
    loaded.bus.undo()
    assert services.kernel.drawing_dimension_styles == original
    assert not services.kernel.sketches and not services.kernel.drawing_rasters
    loaded.bus.redo()
    path = tmp_path / "mixed-style.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_dimension_styles == styles
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (image,)


def test_clipboard_prepare_imports_styles_without_changing_current_style(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    original = services.kernel.drawing_dimension_styles
    imported = DimensionStyle("源样式", arrow_first="filled")
    styles = DimensionStyleTable((*original.styles, imported), original.current_name)
    loaded.bus.execute(
        "drawing.clipboard.prepare",
        {
            "layers": services.kernel.drawing_layers.to_mapping(),
            "dimension_layer": services.kernel.dimension_layer,
            "assignments": [],
            "clipboard_styles": styles.to_mapping(),
        },
        "local",
        version=6,
    )
    assert services.kernel.drawing_dimension_styles == styles
    loaded.bus.undo()
    assert services.kernel.drawing_dimension_styles == original
    loaded.bus.redo()
    assert services.kernel.drawing_dimension_styles == styles
    path = tmp_path / "clipboard-prepare.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_dimension_styles == styles


def test_sketch_create_with_imported_style_is_one_replayable_operation(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    original = services.kernel.drawing_dimension_styles
    style = DimensionStyle("导入样式", arrow_first="filled", center_mark="line")
    styles = DimensionStyleTable((*original.styles, style), original.current_name)
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
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    loaded.bus.execute(
        "sketch.create",
        sketch.to_state_mapping() | {"clipboard_styles": styles.to_mapping()},
        "local",
        version=45,
    )
    assert services.kernel.drawing_dimension_styles == styles and services.kernel.sketches == (
        sketch,
    )
    loaded.bus.undo()
    assert services.kernel.drawing_dimension_styles == original and not services.kernel.sketches
    loaded.bus.redo()
    path = tmp_path / "imported-style.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_dimension_styles == styles and services.kernel.sketches == (
        sketch,
    )


def test_imported_style_upgrades_v7_drawing_and_replays(tmp_path: Path) -> None:
    from mycad.core.document import Document

    services = app.build_app(discoverers=())
    legacy = Document(
        services.registry, archive_version=7, document_type="drawing2d", drawing_fillet_baseline=0
    )
    path = tmp_path / "legacy.my2d"
    save_document(legacy, path)
    loaded = app.open_app_document(services, path)
    original = services.kernel.drawing_dimension_styles
    style = DimensionStyle("导入", arrow_first="filled", center_mark="line")
    table = DimensionStyleTable((*original.styles, style), original.current_name)
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
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, imported_styles=table)
    assert loaded.document.archive_version == 8
    assert (
        services.kernel.sketches == (sketch,) and services.kernel.drawing_dimension_styles == table
    )
    loaded.bus.undo()
    assert not services.kernel.sketches and services.kernel.drawing_dimension_styles == original
    loaded.bus.redo()
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert (
        reopened.kernel.sketches == (sketch,) and reopened.kernel.drawing_dimension_styles == table
    )


def test_failed_sketch_style_import_leaves_document_unchanged() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    original = services.kernel.drawing_dimension_styles
    style = DimensionStyle("导入")
    table = DimensionStyleTable((*original.styles, style), original.current_name)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        100,
        "mm",
        driving=True,
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    with pytest.raises(ValidationError):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0, imported_styles=table)
    assert not loaded.document.commands and not services.kernel.sketches
    assert services.kernel.drawing_dimension_styles == original
