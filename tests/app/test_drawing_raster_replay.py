# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Embedded drawing images follow the normal replay and undo path."""

import base64
import struct
import zlib
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document


def _image() -> DrawingRaster:
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
    return DrawingRaster(uuid4().hex, base64.b64encode(png).decode("ascii"), (2, 3), 20, 10)


def test_raster_commands_undo_redo_and_reopen(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    image = _image()
    loaded.bus.execute("drawing.raster.add", image.to_mapping(), "local", version=1)
    assert services.kernel.drawing_rasters == (image,)
    updated = image.to_mapping() | {"origin_mm": [12, 13], "width_mm": 40}
    loaded.bus.execute("drawing.raster.update", updated, "local", version=1)
    assert services.kernel.drawing_rasters == (DrawingRaster.from_mapping(updated),)
    loaded.bus.undo()
    assert services.kernel.drawing_rasters == (image,)
    loaded.bus.redo()
    expected = services.kernel.drawing_rasters
    path = tmp_path / "raster.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_rasters == expected
    reopened.bus.execute("drawing.raster.remove", {"image_id": image.image_id}, "local", version=1)
    assert not services.kernel.drawing_rasters
    reopened.bus.undo()
    assert services.kernel.drawing_rasters == expected


def test_sketch_and_raster_create_is_atomic_and_replays(tmp_path: Path) -> None:
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    image = _image()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    batch = {"action": "add", "images": [image.to_mapping(version=2)]}
    params = sketch.to_state_mapping() | {"raster_batch": batch}
    part = app.new_document(services)
    with pytest.raises(ValidationError, match="独立二维"):
        part.bus.execute("sketch.create", params, "local", version=29)
    assert not part.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "sketch.create",
            params
            | {
                "raster_batch": {
                    "action": "add",
                    "images": [image.to_mapping(version=2), image.to_mapping(version=2)],
                }
            },
            "local",
            version=29,
        )
    assert not loaded.document.commands and not services.kernel.sketches
    assert not services.kernel.drawing_rasters
    loaded.bus.execute("sketch.create", params, "local", version=29)
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (image,)
    other = _image()
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "sketch.create",
            params | {"raster_batch": {"action": "add", "images": [other.to_mapping(version=2)]}},
            "local",
            version=29,
        )
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (image,)
    loaded.bus.undo()
    assert not services.kernel.sketches and not services.kernel.drawing_rasters
    loaded.bus.redo()
    path = tmp_path / "mixed-create.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (image,)


def test_invalid_raster_command_is_atomic() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    image = _image()
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.raster.add", image.to_mapping() | {"png_base64": "bad"}, "local", version=1
        )
    assert not loaded.document.commands and not services.kernel.drawing_rasters


def test_raster_is_restricted_to_independent_drawings() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services)
    with pytest.raises(ValidationError, match="独立二维"):
        loaded.bus.execute("drawing.raster.add", _image().to_mapping(), "local", version=1)
    assert not loaded.document.commands


def test_dxf_export_reports_unexported_images(tmp_path: Path) -> None:
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.formats.providers.dxf_provider import DXF_PROVIDER, DxfExchangeReport

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    loaded.bus.execute("drawing.raster.add", _image().to_mapping(), "local", version=1)
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    report = DXF_PROVIDER.write(services.kernel, tmp_path / "image.dxf")
    assert isinstance(report, DxfExchangeReport)
    assert any("图片未导出" in warning for warning in report.warnings)


def test_raster_batch_is_atomic_and_undoes_as_one_step(tmp_path: Path) -> None:
    from dataclasses import replace

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    first, second = _image(), _image()
    for image in (first, second):
        loaded.bus.execute("drawing.raster.add", image.to_mapping(), "local", version=1)
    moved_first = replace(first, origin_mm=(30, 40), angle_deg=30)
    moved_second = replace(second, origin_mm=(40, 50), mirrored=True)
    before = loaded.document.command_count
    bad = replace(moved_second, image_id=uuid4().hex)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.raster.batch",
            {
                "action": "update",
                "images": [moved_first.to_mapping(version=2), bad.to_mapping(version=2)],
            },
            "local",
        )
    assert loaded.document.command_count == before
    assert services.kernel.drawing_rasters == (first, second)
    loaded.bus.execute(
        "drawing.raster.batch",
        {
            "action": "update",
            "images": [moved_first.to_mapping(version=2), moved_second.to_mapping(version=2)],
        },
        "local",
    )
    assert services.kernel.drawing_rasters == (moved_first, moved_second)
    loaded.bus.undo()
    assert services.kernel.drawing_rasters == (first, second)
    loaded.bus.redo()
    path = tmp_path / "batch.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_rasters == (moved_first, moved_second)
    reopened.bus.execute(
        "drawing.raster.batch",
        {"action": "remove", "image_ids": [first.image_id, second.image_id]},
        "local",
    )
    assert not services.kernel.drawing_rasters
    reopened.bus.undo()
    assert services.kernel.drawing_rasters == (moved_first, moved_second)


def test_raster_batch_rejects_duplicate_id_and_can_add() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    first, second = _image(), _image()
    items = [first.to_mapping(version=2), second.to_mapping(version=2)]
    loaded.bus.execute("drawing.raster.batch", {"action": "add", "images": items}, "local")
    assert services.kernel.drawing_rasters == (first, second)
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.raster.batch",
            {"action": "remove", "image_ids": [first.image_id, first.image_id]},
            "local",
        )
    assert loaded.document.command_count == count
    assert services.kernel.drawing_rasters == (first, second)
    loaded.bus.undo()
    assert not services.kernel.drawing_rasters
    loaded.bus.redo()
    assert services.kernel.drawing_rasters == (first, second)


def test_mixed_raster_sketch_revision_is_atomic_and_replays(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    image = _image()
    loaded.bus.execute("drawing.raster.add", image.to_mapping(), "local", version=1)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    moved = replace(sketch, entities=(replace(line, start_mm=(3, 4), end_mm=(13, 4)),))
    state = moved.to_state_mapping()
    revision = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    moved_image = replace(image, origin_mm=(5, 7))
    batch = {"action": "update", "images": [moved_image.to_mapping(version=2)]}
    params = {"revisions": [revision], "raster_batch": batch}
    count = loaded.document.command_count
    bad_image = replace(moved_image, image_id=uuid4().hex)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise",
            params
            | {"raster_batch": {"action": "update", "images": [bad_image.to_mapping(version=2)]}},
            "local",
            version=47,
        )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise",
            params | {"revisions": [revision | {"base_state_sha256": "0" * 64}]},
            "local",
            version=47,
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_rasters == (image,)
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=47)
    assert services.kernel.sketches == (moved,)
    assert services.kernel.drawing_rasters == (moved_image,)
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_rasters == (image,)
    loaded.bus.redo()
    path = tmp_path / "mixed.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.sketches == (moved,)
    assert services.kernel.drawing_rasters == (moved_image,)


def test_dimension_layer_revision_rejects_other_constraint_changes_and_replays(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from mycad.core.sketch import LineEntity, Sketch, SketchLayer, SketchLayerTable, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    image = _image()
    loaded.bus.execute("drawing.raster.add", image.to_mapping(), "local", version=1)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        layer_name="0",
    )
    layers = SketchLayerTable().add(SketchLayer("目标"))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,), layers=layers)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)

    def params_for(updated: Sketch) -> dict[str, object]:
        state = updated.to_state_mapping()
        return {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        }

    bad = replace(sketch, constraints=(replace(dimension, layer_name="目标", value=20),))
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params_for(bad), "local", version=52)
    assert loaded.document.command_count == count
    updated = replace(
        sketch,
        entities=(replace(line, layer_name="目标"),),
        constraints=(replace(dimension, layer_name="目标"),),
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params_for(updated), "local", version=50)
    assert loaded.document.command_count == count
    loaded.bus.execute("drawing.sketch.revise", params_for(updated), "local", version=52)
    assert services.kernel.sketches[0].entities == updated.entities
    assert services.kernel.sketches[0].constraints == updated.constraints
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints == sketch.constraints
    loaded.bus.redo()
    path = tmp_path / "dimension-layer.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.sketches[0].constraints == updated.constraints


def test_dimension_text_with_mixed_raster_create_and_move_replays(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    image = _image()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        text_override="宽 <> mm",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    params = sketch.to_state_mapping() | {
        "raster_batch": {"action": "add", "images": [image.to_mapping(version=2)]}
    }
    loaded.bus.execute("sketch.create", params, "local", version=31)
    moved = replace(sketch, entities=(replace(line, start_mm=(3, 4), end_mm=(13, 4)),))
    state = moved.to_state_mapping()
    revision = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    moved_image = replace(image, origin_mm=(5, 7))
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [revision],
            "raster_batch": {"action": "update", "images": [moved_image.to_mapping(version=2)]},
        },
        "local",
        version=49,
    )
    path = tmp_path / "mixed-text-raster.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == (moved,)
    assert services.kernel.drawing_rasters == (moved_image,)
    reopened.bus.undo()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_rasters == (image,)
