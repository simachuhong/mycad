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


@pytest.mark.parametrize("action", ["add", "update", "remove"])
@pytest.mark.parametrize("layer_state", ["locked", "frozen", "hidden"])
def test_raster_batch_v2_rejects_locked_layer_atomically_and_preserves_v1(
    tmp_path: Path, action: str, layer_state: str
) -> None:
    from dataclasses import replace

    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    layers = services.kernel.drawing_layers.add(SketchLayer("LOCK"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    first, second = _image(), replace(_image(), layer_name="LOCK")
    if action != "add":
        loaded.bus.execute(
            "drawing.raster.batch",
            {
                "action": "add",
                "images": [first.to_mapping(version=2), second.to_mapping(version=2)],
            },
            "local",
            version=1,
        )
    guarded = layers.replace(
        replace(
            layers.get("LOCK"),
            **({"visible": False} if layer_state == "hidden" else {layer_state: True}),
        )
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": guarded.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    if action == "remove":
        params = {"action": action, "image_ids": [first.image_id, second.image_id]}
    elif action == "update":
        params = {
            "action": action,
            "images": [
                replace(first, origin_mm=(8, 8)).to_mapping(version=2),
                replace(second, origin_mm=(9, 9)).to_mapping(version=2),
            ],
        }
    else:
        params = {
            "action": action,
            "images": [first.to_mapping(version=2), second.to_mapping(version=2)],
        }
    before, original = loaded.document.commands, services.kernel.drawing_rasters
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.raster.batch", params, "local", version=2)
    assert loaded.document.commands == before and services.kernel.drawing_rasters == original
    loaded.bus.execute("drawing.raster.batch", params, "local", version=1)
    legacy_result = services.kernel.drawing_rasters
    path = tmp_path / "legacy-locked-raster.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_rasters == legacy_result


@pytest.mark.parametrize("locked_source", [False, True])
def test_raster_batch_v2_rejects_moving_to_or_from_locked_layer(locked_source: bool) -> None:
    from dataclasses import replace

    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    layers = services.kernel.drawing_layers.add(SketchLayer("LOCK"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    image = replace(_image(), layer_name="LOCK" if locked_source else "0")
    loaded.bus.execute(
        "drawing.raster.batch",
        {"action": "add", "images": [image.to_mapping(version=2)]},
        "local",
        version=1,
    )
    locked = layers.replace(replace(layers.get("LOCK"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    changed = replace(image, layer_name="0" if locked_source else "LOCK")
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.raster.batch",
            {"action": "update", "images": [changed.to_mapping(version=2)]},
            "local",
            version=2,
        )
    assert loaded.document.commands == before and services.kernel.drawing_rasters == (image,)


@pytest.mark.parametrize("action", ["add", "update", "remove"])
@pytest.mark.parametrize("layer_state", ["locked", "frozen", "hidden"])
def test_single_raster_new_versions_protect_layer_and_replay_old_history(
    tmp_path: Path, action: str, layer_state: str
) -> None:
    from dataclasses import replace

    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    layers = services.kernel.drawing_layers.add(SketchLayer("LOCK"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    image = replace(_image(), layer_name="LOCK")
    if action != "add":
        loaded.bus.execute("drawing.raster.add", image.to_mapping(version=2), "local", version=2)
    guarded = layers.replace(
        replace(
            layers.get("LOCK"),
            **({"visible": False} if layer_state == "hidden" else {layer_state: True}),
        )
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": guarded.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    params = (
        {"image_id": image.image_id}
        if action == "remove"
        else replace(image, origin_mm=(9, 9)).to_mapping(version=2)
        if action == "update"
        else image.to_mapping(version=2)
    )
    old_version = 1 if action == "remove" else 2
    new_version = 2 if action == "remove" else 3
    before, original = loaded.document.commands, services.kernel.drawing_rasters
    with pytest.raises(ValidationError):
        loaded.bus.execute(f"drawing.raster.{action}", params, "local", version=new_version)
    assert loaded.document.commands == before and services.kernel.drawing_rasters == original
    loaded.bus.execute(f"drawing.raster.{action}", params, "local", version=old_version)
    expected = services.kernel.drawing_rasters
    path = tmp_path / "old-single-raster.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_rasters == expected


@pytest.mark.parametrize("locked_source", [False, True])
def test_single_raster_v3_rejects_moving_to_or_from_locked_layer(locked_source: bool) -> None:
    from dataclasses import replace

    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    layers = services.kernel.drawing_layers.add(SketchLayer("LOCK"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    image = replace(_image(), layer_name="LOCK" if locked_source else "0")
    loaded.bus.execute("drawing.raster.add", image.to_mapping(version=2), "local", version=2)
    locked = layers.replace(replace(layers.get("LOCK"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    changed = replace(image, layer_name="0" if locked_source else "LOCK")
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.raster.update", changed.to_mapping(version=2), "local", version=3
        )
    assert loaded.document.commands == before and services.kernel.drawing_rasters == (image,)


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


@pytest.mark.parametrize("action", ["add", "update", "remove"])
@pytest.mark.parametrize("layer_state", ["locked", "frozen", "hidden"])
def test_mixed_sketch_revision_v63_protects_raster_layer_and_replays_v62(
    tmp_path: Path, action: str, layer_state: str
) -> None:
    from dataclasses import replace

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    layers = services.kernel.drawing_layers.add(SketchLayer("LOCK"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    image = replace(_image(), layer_name="LOCK")
    if action != "add":
        loaded.bus.execute("drawing.raster.add", image.to_mapping(version=2), "local", version=2)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    guarded = layers.replace(
        replace(
            layers.get("LOCK"),
            **({"visible": False} if layer_state == "hidden" else {layer_state: True}),
        )
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": guarded.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    current = services.kernel.sketches[0]
    changed = replace(current, entities=(replace(line, end_mm=(12, 0)),))
    state = changed.to_state_mapping()
    batch = (
        {"action": "remove", "image_ids": [image.image_id]}
        if action == "remove"
        else {"action": action, "images": [replace(image, origin_mm=(8, 9)).to_mapping(version=2)]}
    )
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "raster_batch": batch,
    }
    before, old_images = loaded.document.commands, services.kernel.drawing_rasters
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=63)
    assert loaded.document.commands == before and services.kernel.sketches == (current,)
    assert services.kernel.drawing_rasters == old_images
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=62)
    expected = services.kernel.drawing_rasters
    path = tmp_path / "legacy-mixed-revision.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_rasters == expected


@pytest.mark.parametrize("locked_source", [False, True])
def test_mixed_sketch_revision_v63_checks_both_image_layers(locked_source: bool) -> None:
    from dataclasses import replace

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    layers = services.kernel.drawing_layers.add(SketchLayer("LOCK"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    image = replace(_image(), layer_name="LOCK" if locked_source else "0")
    loaded.bus.execute("drawing.raster.add", image.to_mapping(version=2), "local", version=2)
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (10, 0)),), layers=layers
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    locked = layers.replace(replace(layers.get("LOCK"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    current = services.kernel.sketches[0]
    state = current.to_state_mapping()
    changed_image = replace(image, layer_name="0" if locked_source else "LOCK")
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "raster_batch": {"action": "update", "images": [changed_image.to_mapping(version=2)]},
    }
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=63)
    assert loaded.document.commands == before and services.kernel.drawing_rasters == (image,)


def test_mixed_sketch_create_v56_protects_raster_layer_and_replays_v55(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    layers = services.kernel.drawing_layers.add(SketchLayer("LOCK"))
    locked = layers.replace(replace(layers.get("LOCK"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    image = replace(_image(), layer_name="LOCK")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), layers=locked)
    params = sketch.to_state_mapping() | {
        "raster_batch": {"action": "add", "images": [image.to_mapping(version=2)]},
        "clipboard_styles": services.kernel.drawing_dimension_styles.to_mapping(),
    }
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("sketch.create", params, "local", version=56)
    assert (
        loaded.document.commands == before
        and not services.kernel.sketches
        and not services.kernel.drawing_rasters
    )
    loaded.bus.execute("sketch.create", params, "local", version=55)
    path = tmp_path / "legacy-mixed-create.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.drawing_rasters == (image,)


@pytest.mark.parametrize("styled", [False, True])
def test_mixed_sketch_create_v56_accepts_valid_payload_with_optional_styles(
    tmp_path: Path, styled: bool
) -> None:
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    image = _image()
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (10, 0)),))
    params = sketch.to_state_mapping() | {
        "raster_batch": {"action": "add", "images": [image.to_mapping(version=2)]}
    }
    if styled:
        params["clipboard_styles"] = services.kernel.drawing_dimension_styles.to_mapping()
    loaded.bus.execute("sketch.create", params, "local", version=56)
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (image,)
    loaded.bus.undo()
    assert not services.kernel.sketches and not services.kernel.drawing_rasters
    loaded.bus.redo()
    path = tmp_path / "protected-mixed-create.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_rasters == (image,)


def test_mixed_sketch_create_v56_accepts_dimension_and_text_styles() -> None:
    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    image = _image()
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (10, 0)),))
    fonts = TextStyleTable((TextStyle(), TextStyle("custom", "字体", "Font A")))
    styles = DimensionStyleTable(
        (DimensionStyle("标准"), DimensionStyle("custom", text_style_id="custom")), "标准"
    )
    params = sketch.to_state_mapping() | {
        "raster_batch": {"action": "add", "images": [image.to_mapping(version=2)]},
        "clipboard_styles": styles.to_mapping(),
        "clipboard_text_styles": fonts.to_mapping(),
    }
    loaded.bus.execute("sketch.create", params, "local", version=56)
    assert services.kernel.drawing_rasters == (image,)
    assert services.kernel.drawing_text_styles.get("custom").font_family == "Font A"
    assert services.kernel.drawing_dimension_styles.get("custom").text_style_id == "custom"


def test_protected_mixed_raster_revision_preserves_dimension_tolerance(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad.core.dimension_tolerance import DimensionTolerance
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
        tolerance=DimensionTolerance("deviation", 0.02, -0.01, 3),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    loaded.bus.execute(
        "sketch.create",
        sketch.to_state_mapping()
        | {"raster_batch": {"action": "add", "images": [image.to_mapping(version=2)]}},
        "local",
        version=56,
    )
    moved = replace(sketch, entities=(replace(line, start_mm=(3, 4), end_mm=(13, 4)),))
    state = moved.to_state_mapping()
    moved_image = replace(image, origin_mm=(5, 7))
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
            ],
            "raster_batch": {"action": "update", "images": [moved_image.to_mapping(version=2)]},
        },
        "local",
        version=63,
    )
    path = tmp_path / "mixed-tolerance-raster.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == (moved,)
    assert services.kernel.drawing_rasters == (moved_image,)
    reopened.bus.undo()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_rasters == (image,)
    reopened.bus.redo()
    assert services.kernel.sketches == (moved,)
    assert services.kernel.drawing_rasters == (moved_image,)
