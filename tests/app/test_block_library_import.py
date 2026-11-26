# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Block library provenance survives document replay and candidate transactions."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.drawing_blocks import BlockDefinition
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity


def test_library_origin_command_lifecycle(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(uuid4().hex, "块", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ())
    params = {
        "definition_id": definition.definition_id,
        "asset_id": uuid4().hex,
        "content_sha256": "a" * 64,
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.block_library.bind", params, "local", version=1)
    batch = {
        "operations": [
            {"id": "drawing.block.create", "version": 1, "params": definition.to_mapping()},
            {"id": "drawing.block_library.bind", "version": 1, "params": params},
        ]
    }
    loaded.bus.execute("drawing.objects.batch", batch, "local", version=1)
    origins = services.kernel.drawing_block_library_origins
    assert len(origins) == 1 and origins[0].asset_id == params["asset_id"]
    assert app.drawing_collection_snapshot(services).block_library_origins == origins
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.block_library.bind", {**params, "asset_id": uuid4().hex}, "local", version=1
        )
    path = tmp_path / "origin.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_block_library_origins == origins
    reopened.bus.undo_operation()
    assert not services.kernel.drawing_block_library_origins
    reopened.bus.redo_operation()
    assert services.kernel.drawing_block_library_origins == origins
    reopened.bus.execute(
        "drawing.block.remove", {"definition_id": definition.definition_id}, "local"
    )
    assert not services.kernel.drawing_block_library_origins
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_library_origins == origins


def test_origin_survives_optimized_rebuild_and_failed_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    params = {
        "definition_id": definition.definition_id,
        "asset_id": uuid4().hex,
        "content_sha256": "b" * 64,
    }
    operations = [
        {"id": "drawing.block.create", "version": 1, "params": definition.to_mapping()},
        {"id": "drawing.block_library.bind", "version": 1, "params": params},
    ]
    loaded.bus.execute("drawing.objects.batch", {"operations": operations}, "local")
    origin = services.kernel.drawing_block_library_origins
    history = tuple(loaded.document.commands)
    bad = [
        {
            "id": "drawing.block_library.bind",
            "version": 1,
            "params": {**params, "asset_id": uuid4().hex},
        }
    ]
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.objects.batch", {"operations": bad}, "local")
    assert tuple(loaded.document.commands) == history
    assert services.kernel.drawing_block_library_origins == origin
    regenerate = cast(
        "Callable[..., object]", vars(type(services.kernel))["_regenerate_with_sketches"]
    )
    calls = 0

    def track(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return regenerate(services.kernel, *args, **kwargs)

    monkeypatch.setattr(services.kernel, "_regenerate_with_sketches", track)
    revised = replace(sketch, entities=(replace(line, end_mm=(3, 0)),))
    state = revised.to_state_mapping()
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
        version=52,
    )
    assert calls > 0 and services.kernel.drawing_block_library_origins == origin


def test_origin_rejected_outside_independent_drawing() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    params = {"definition_id": uuid4().hex, "asset_id": uuid4().hex, "content_sha256": "a" * 64}
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.block_library.bind", params, "local")


def test_repeat_library_insert_after_reopen_reuses_definition(tmp_path: Path) -> None:
    from mycad.core.block_library import BlockAsset
    from mycad.core.block_library_import import BlockPlacement, prepare_block_library_import
    from mycad.core.drawing_text import DrawingText, TextStyleTable
    from mycad.core.sketch_layers import SketchLayerTable

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(
        uuid4().hex,
        "库块",
        (LineEntity(uuid4().hex, (0, 0), (2, 0)),),
        (DrawingText(uuid4().hex, "A", (1, 2)),),
    )
    asset = BlockAsset(
        uuid4().hex, "库块", "", (), definition, TextStyleTable(), SketchLayerTable()
    )
    first = prepare_block_library_import(
        asset,
        app.drawing_collection_snapshot(services),
        placement=BlockPlacement((2, 3), 0, 1, "0"),
    )
    assert first.operation is not None
    loaded.bus.execute(first.operation.command_id, first.operation.params, "local", version=1)
    second = prepare_block_library_import(
        asset,
        app.drawing_collection_snapshot(services),
        placement=BlockPlacement((4, 5), 30, 2, "0"),
    )
    assert second.definition_id == first.definition_id and second.instance_id != first.instance_id
    assert second.operation is not None
    loaded.bus.execute(second.operation.command_id, second.operation.params, "local", version=1)
    assert len(services.kernel.drawing_block_definitions) == 1
    path = tmp_path / "library.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    third = prepare_block_library_import(
        asset,
        app.drawing_collection_snapshot(services),
        placement=BlockPlacement((8, 0), 0, 1, "0"),
    )
    assert third.definition_id == first.definition_id
    assert third.operation is not None
    reopened.bus.execute(third.operation.command_id, third.operation.params, "local", version=1)
    assert len(services.kernel.drawing_block_definitions) == 1
    assert len(services.kernel.drawing_block_instances) == 3
    reopened.bus.undo_operation()
    assert len(services.kernel.drawing_block_instances) == 2


def test_import_after_bedit_delete_and_reopen_reuses_remaining_copy(tmp_path: Path) -> None:
    from mycad.core.block_library import BlockAsset
    from mycad.core.block_library_import import BlockPlacement, prepare_block_library_import
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch_layers import SketchLayerTable

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    asset = BlockAsset(uuid4().hex, "B", "", (), definition, TextStyleTable(), SketchLayerTable())

    def insert() -> str:
        result = prepare_block_library_import(
            asset,
            app.drawing_collection_snapshot(services),
            placement=BlockPlacement((0, 0), 0, 1, "0"),
        )
        assert result.operation is not None
        loaded.bus.execute(result.operation.command_id, result.operation.params, "local", version=1)
        return result.definition_id

    original = insert()
    first = services.kernel.drawing_block_definitions[0]
    changed_line = replace(first.entities[0], end_mm=(4, 0))
    loaded.bus.execute(
        "drawing.block.update", replace(first, entities=(changed_line,)).to_mapping(), "local"
    )
    new_id = insert()
    assert new_id != original
    first_instance = services.kernel.drawing_block_instances[0]
    loaded.bus.execute(
        "drawing.block_instance.remove", {"instance_id": first_instance.instance_id}, "local"
    )
    loaded.bus.execute("drawing.block.remove", {"definition_id": original}, "local")
    path = tmp_path / "deleted-old.my2d"
    save_document(loaded.document, path)
    loaded = app.open_app_document(services, path)
    assert insert() == new_id
    assert len(services.kernel.drawing_block_definitions) == 1


def test_definition_only_import_is_noop_on_repeat() -> None:
    from mycad.core.block_library import BlockAsset
    from mycad.core.block_library_import import prepare_block_library_import
    from mycad.core.drawing_text import DrawingText, TextStyleTable
    from mycad.core.sketch_layers import SketchLayerTable

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(
        uuid4().hex, "文字块", (), (DrawingText(uuid4().hex, "Text", (0, 0)),)
    )
    asset = BlockAsset(
        uuid4().hex, "文字块", "", (), definition, TextStyleTable(), SketchLayerTable()
    )
    result = prepare_block_library_import(
        asset, app.drawing_collection_snapshot(services), placement=None
    )
    assert result.operation is not None
    loaded.bus.execute(result.operation.command_id, result.operation.params, "local", version=1)
    repeat = prepare_block_library_import(
        asset, app.drawing_collection_snapshot(services), placement=None
    )
    assert repeat.operation is None and repeat.definition_id == result.definition_id
    assert not services.kernel.drawing_block_instances


def test_conflicting_resources_repeat_without_growth() -> None:
    from mycad.core.block_library import BlockAsset
    from mycad.core.block_library_import import BlockPlacement, prepare_block_library_import
    from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    view = app.drawing_collection_snapshot(services)
    layers = view.layers.add(SketchLayer("Ink", color_rgb=(20, 30, 40)))
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": layers.to_mapping(), "dimension_layer": view.dimension_layer},
        "local",
    )
    original_style = TextStyle(style_id="shared", name="Shared", height_mm=4)
    styles = TextStyleTable((*view.text_styles.styles, original_style), view.text_styles.current_id)
    loaded.bus.execute(
        "drawing.text.batch",
        {"add": [], "update": [], "remove": [], "styles": styles.to_mapping()},
        "local",
    )
    source_style = TextStyle(style_id="shared", name="Shared", height_mm=7)
    definition = BlockDefinition(
        uuid4().hex,
        "B",
        (LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="Ink"),),
        (DrawingText(uuid4().hex, "A", (0, 1), style_id="shared", layer_name="Ink"),),
    )
    asset = BlockAsset(
        uuid4().hex,
        "B",
        "",
        (),
        definition,
        TextStyleTable((source_style,), "shared"),
        SketchLayerTable((SketchLayer("0"), SketchLayer("Ink", color_rgb=(80, 90, 100)))),
    )
    first = prepare_block_library_import(
        asset,
        app.drawing_collection_snapshot(services),
        placement=BlockPlacement((0, 0), 0, 1, "0"),
    )
    assert first.operation is not None and first.issues
    loaded.bus.execute(first.operation.command_id, first.operation.params, "local")
    after = app.drawing_collection_snapshot(services)
    assert after.layers.get("Ink").color_rgb == (20, 30, 40)
    assert after.layers.get("Ink 副本").color_rgb == (80, 90, 100)
    second = prepare_block_library_import(asset, after, placement=BlockPlacement((5, 0), 0, 1, "0"))
    assert second.definition_id == first.definition_id and second.operation is not None
    loaded.bus.execute(second.operation.command_id, second.operation.params, "local")
    updated = app.drawing_collection_snapshot(services)
    assert updated.layers == after.layers and updated.text_styles == after.text_styles
    assert len(updated.block_definitions) == 1 and len(updated.block_instances) == 2


def test_import_batch_undo_reopen_and_locked_target(tmp_path: Path) -> None:
    from mycad.core.block_library import BlockAsset
    from mycad.core.block_library_import import BlockPlacement, prepare_block_library_import
    from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    source_style = TextStyle(style_id="asset-font", name="Asset font", height_mm=8)
    definition = BlockDefinition(
        uuid4().hex,
        "B",
        (),
        (DrawingText(uuid4().hex, "Text", (0, 0), style_id="asset-font", layer_name="Asset"),),
    )
    asset = BlockAsset(
        uuid4().hex,
        "B",
        "",
        (),
        definition,
        TextStyleTable((source_style,), "asset-font"),
        SketchLayerTable((SketchLayer("0"), SketchLayer("Asset"))),
    )
    before = app.drawing_collection_snapshot(services)
    result = prepare_block_library_import(
        asset, before, placement=BlockPlacement((0, 0), 0, 1, "0")
    )
    assert result.operation is not None
    loaded.bus.execute(result.operation.command_id, result.operation.params, "local", version=1)
    path = tmp_path / "atomic.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    after = app.drawing_collection_snapshot(services)
    assert after.layers == before.layers and after.text_styles == before.text_styles
    assert (
        not after.block_definitions
        and not after.block_instances
        and not after.block_library_origins
    )
    reopened.bus.redo_operation()
    assert len(services.kernel.drawing_block_instances) == 1
    layers = after.layers.add(SketchLayer("Asset", locked=True))
    locked = replace(before, layers=layers)
    with pytest.raises(ValidationError, match="锁定"):
        prepare_block_library_import(asset, locked, placement=BlockPlacement((0, 0), 0, 1, "0"))


def test_curve_identity_and_distinct_asset_id_import() -> None:
    from mycad.core.block_library import BlockAsset
    from mycad.core.block_library_import import BlockPlacement, prepare_block_library_import
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_layers import SketchLayerTable

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    curve = PolylineEntity(
        uuid4().hex, ((0, 0), (1, 0), (2, 1)), point_ids=tuple(uuid4().hex for _ in range(3))
    )
    definition = BlockDefinition(uuid4().hex, "B", (curve,), ())
    asset = BlockAsset(uuid4().hex, "B", "", (), definition, TextStyleTable(), SketchLayerTable())
    first = prepare_block_library_import(
        asset,
        app.drawing_collection_snapshot(services),
        placement=BlockPlacement((0, 0), 0, 1, "0"),
    )
    assert first.operation is not None
    loaded.bus.execute(first.operation.command_id, first.operation.params, "local")
    imported = services.kernel.drawing_block_definitions[0].entities[0]
    assert isinstance(imported, PolylineEntity)
    assert imported.entity_id != curve.entity_id and not set(imported.point_ids) & set(
        curve.point_ids
    )
    second = prepare_block_library_import(
        asset,
        app.drawing_collection_snapshot(services),
        placement=BlockPlacement((1, 0), 0, 1, "0"),
    )
    assert second.definition_id == first.definition_id
    another_asset = replace(asset, asset_id=uuid4().hex)
    third = prepare_block_library_import(
        another_asset, app.drawing_collection_snapshot(services), placement=None
    )
    assert third.definition_id != first.definition_id and third.operation is not None
