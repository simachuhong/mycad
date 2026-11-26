# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Imported geometry, text, layers and font styles form one document operation."""

import base64
import struct
import zlib
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable


def test_text_only_import_prepares_layers_without_empty_sketch_and_undoes_once(
    tmp_path: Path,
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    original_layers = services.kernel.drawing_layers
    source_layer = SketchLayer("TEXT", color_rgb=(200, 20, 30))
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (), layers=SketchLayerTable().add(source_layer)
    )
    style = TextStyle("technical", "Technical", "Missing family", height_mm=5)
    source_styles = TextStyleTable((TextStyle(), style))
    text = DrawingText(
        uuid4().hex, "Imported note", (1, 2), style_id="technical", layer_name="TEXT"
    )
    app.commit_new_sketch(
        services,
        loaded,
        sketch,
        session_identity=1,
        imported_texts=(text,),
        imported_text_styles=source_styles,
    )
    assert services.kernel.drawing_texts == (text,)
    assert not services.kernel.sketches
    assert all(command.id != "sketch.create" for command in loaded.document.commands)
    assert services.kernel.drawing_layers.get("TEXT") == source_layer
    assert services.kernel.drawing_text_styles.get("technical") == style
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_texts
    assert services.kernel.drawing_layers == original_layers
    assert services.kernel.drawing_text_styles == TextStyleTable()
    loaded.bus.redo_operation()
    target = tmp_path / "text-import.my2d"
    save_document(loaded.document, target)
    app.open_app_document(services, target)
    assert services.kernel.drawing_texts == (text,)
    assert not services.kernel.sketches


def test_mixed_import_remaps_style_collisions_and_retains_existing_layer_properties() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    old_style = TextStyle("standard", "Technical", "Existing font")
    old_table = TextStyleTable((old_style,))
    loaded.bus.execute("drawing.text_styles.set", old_table.to_mapping(), "local")
    old = DrawingText(uuid4().hex, "Existing", (0, 0))
    loaded.bus.execute("drawing.text.add", old.to_mapping(), "local")
    layer = SketchLayer("TEXT", color_rgb=(10, 20, 30))
    layers = services.kernel.drawing_layers.add(layer)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": layers.to_mapping(), "dimension_layer": services.kernel.dimension_layer},
        "local",
    )
    incoming_style = replace(old_style, font_family="Imported font", name="technical")
    incoming_layers = SketchLayerTable().add(replace(layer, color_rgb=(200, 100, 0)))
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="TEXT")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), layers=incoming_layers)
    text = replace(old, text="Imported", layer_name="TEXT")
    before = loaded.document.command_count
    app.commit_new_sketch(
        services,
        loaded,
        sketch,
        session_identity=1,
        imported_texts=(text,),
        imported_text_styles=TextStyleTable((incoming_style,)),
    )
    assert services.kernel.drawing_texts[0] == old
    imported = services.kernel.drawing_texts[1]
    assert imported.text_id != old.text_id
    assert imported.style_id != old.style_id
    table = services.kernel.drawing_text_styles
    assert table.get("standard") == old_style
    assert table.get(imported.style_id).font_family == "Imported font"
    assert table.get(imported.style_id).name.casefold() != "technical"
    assert services.kernel.drawing_layers.get("TEXT") == layer
    assert services.kernel.sketches[0].layers.get("TEXT") == layer
    loaded.bus.undo_operation()
    assert loaded.document.command_count == before
    assert services.kernel.drawing_texts == (old,)
    assert not services.kernel.sketches


def test_invalid_import_cannot_publish_geometry_layers_or_styles() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (10, 0)),))
    text = DrawingText(uuid4().hex, "Missing layer", (0, 0), layer_name="MISSING")
    style = TextStyle("incoming", "Incoming")
    with pytest.raises(ValidationError):
        app.commit_new_sketch(
            services,
            loaded,
            sketch,
            session_identity=1,
            imported_texts=(replace(text, style_id="incoming"),),
            imported_text_styles=TextStyleTable((TextStyle(), style)),
        )
    assert not loaded.document.commands
    assert not services.kernel.sketches
    assert not services.kernel.drawing_texts
    assert services.kernel.drawing_layers == layers
    assert services.kernel.drawing_text_styles == TextStyleTable()


def test_text_only_import_retains_accompanying_dimension_style_table() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    original = services.kernel.drawing_dimension_styles
    source = DimensionStyleTable((DimensionStyle("标准"), DimensionStyle("Imported", 2, 3)), "标准")
    text = DrawingText(uuid4().hex, "Text with no geometry", (0, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    app.commit_new_sketch(
        services,
        loaded,
        sketch,
        session_identity=1,
        imported_texts=(text,),
        imported_styles=source,
    )
    assert services.kernel.drawing_dimension_styles == source
    assert not services.kernel.sketches
    loaded.bus.undo_operation()
    assert services.kernel.drawing_dimension_styles == original
    assert not services.kernel.drawing_texts


@pytest.mark.parametrize("with_geometry", [False, True])
def test_text_and_image_paste_is_one_operation_with_collision_safe_image_identity(
    with_geometry: bool,
) -> None:
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
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    image = DrawingRaster(uuid4().hex, base64.b64encode(png).decode("ascii"), (0, 0), 10, 10)
    loaded.bus.execute("drawing.raster.add", image.to_mapping(version=2), "local")
    layers = SketchLayerTable().add(SketchLayer("PASTE"))
    entities = (LineEntity(uuid4().hex, (0, 0), (10, 0)),) if with_geometry else ()
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities, layers=layers)
    text = DrawingText(uuid4().hex, "Mixed clipboard", (0, 0), layer_name="PASTE")
    before = loaded.document.command_count
    app.commit_new_sketch(
        services,
        loaded,
        sketch,
        session_identity=1,
        imported_texts=(text,),
        imported_rasters=(replace(image, layer_name="PASTE"),),
    )
    assert services.kernel.drawing_texts == (text,)
    assert len(services.kernel.drawing_rasters) == 2
    assert services.kernel.drawing_rasters[0] == image
    assert services.kernel.drawing_rasters[1].image_id != image.image_id
    assert services.kernel.drawing_rasters[1].layer_name == "PASTE"
    assert bool(services.kernel.sketches) == with_geometry
    loaded.bus.undo_operation()
    assert loaded.document.command_count == before
    assert services.kernel.drawing_rasters == (image,)
    assert not services.kernel.drawing_texts
    assert not services.kernel.sketches


def test_repeat_mixed_paste_collision_undo_redo_and_reopen(tmp_path: Path) -> None:
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
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    target_style = TextStyle("standard", "Technical", "Target Font")
    incoming_style = TextStyle("standard", "technical", "Source Font")
    target_styles = TextStyleTable((target_style,))
    incoming_styles = TextStyleTable((incoming_style,))
    loaded.bus.execute("drawing.text_styles.set", target_styles.to_mapping(), "local")
    old = DrawingText(uuid4().hex, "Existing", (0, 0))
    loaded.bus.execute("drawing.text.add", old.to_mapping(), "local")
    image = DrawingRaster(uuid4().hex, base64.b64encode(png).decode("ascii"), (0, 0), 10, 10)
    loaded.bus.execute("drawing.raster.add", image.to_mapping(version=2), "local")
    dimension_styles = services.kernel.drawing_dimension_styles
    layers = services.kernel.drawing_layers.add(SketchLayer("TEXT", color_rgb=(10, 20, 30)))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    incoming_layers = SketchLayerTable().add(SketchLayer("TEXT", color_rgb=(200, 100, 0)))
    source = replace(old, text="Incoming", layer_name="TEXT")
    first_state = None
    for index in range(2):
        sketch = Sketch(
            uuid4().hex,
            WorkPlaneFrame.xy(),
            (LineEntity(uuid4().hex, (index, 0), (index + 5, 0)),),
            layers=incoming_layers,
        )
        app.commit_new_sketch(
            services,
            loaded,
            sketch,
            session_identity=0,
            imported_texts=(source,),
            imported_text_styles=incoming_styles,
            imported_rasters=(replace(image, layer_name="TEXT"),),
        )
        if index == 0:
            first_state = (
                services.kernel.drawing_texts,
                services.kernel.drawing_rasters,
                services.kernel.sketches,
                services.kernel.drawing_text_styles,
            )
    assert first_state is not None
    texts, images = services.kernel.drawing_texts, services.kernel.drawing_rasters
    assert texts[0] == old and len({text.text_id for text in texts}) == 3
    assert len({raster.image_id for raster in images}) == 3
    assert all(
        services.kernel.drawing_text_styles.get(text.style_id).font_family == "Source Font"
        for text in texts[1:]
    )
    assert services.kernel.drawing_text_styles.get("standard") == target_style
    assert services.kernel.drawing_layers.get("TEXT").color_rgb == (10, 20, 30)
    assert services.kernel.drawing_dimension_styles == dimension_styles
    final_state = (texts, images, services.kernel.sketches, services.kernel.drawing_text_styles)
    loaded.bus.undo_operation()
    assert (
        services.kernel.drawing_texts,
        services.kernel.drawing_rasters,
        services.kernel.sketches,
        services.kernel.drawing_text_styles,
    ) == first_state
    loaded.bus.redo_operation()
    assert (
        services.kernel.drawing_texts,
        services.kernel.drawing_rasters,
        services.kernel.sketches,
        services.kernel.drawing_text_styles,
    ) == final_state
    path = tmp_path / "repeat-paste.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert (
        services.kernel.drawing_texts,
        services.kernel.drawing_rasters,
        services.kernel.sketches,
        services.kernel.drawing_text_styles,
    ) == final_state


def test_invalid_imported_style_does_not_publish_any_part() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = SketchLayerTable().add(SketchLayer("TEXT"))
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (5, 0)),), layers=layers
    )
    text = DrawingText(uuid4().hex, "Bad style", (1, 2), style_id="missing", layer_name="TEXT")
    before = (
        loaded.document.commands,
        services.kernel.sketches,
        services.kernel.drawing_texts,
        services.kernel.drawing_text_styles,
        services.kernel.drawing_layers,
        services.kernel.drawing_rasters,
        services.kernel.drawing_dimension_styles,
    )
    with pytest.raises(ValidationError):
        app.commit_new_sketch(
            services,
            loaded,
            sketch,
            session_identity=0,
            imported_texts=(text,),
            imported_text_styles=TextStyleTable(),
        )
    assert (
        loaded.document.commands,
        services.kernel.sketches,
        services.kernel.drawing_texts,
        services.kernel.drawing_text_styles,
        services.kernel.drawing_layers,
        services.kernel.drawing_rasters,
        services.kernel.drawing_dimension_styles,
    ) == before
