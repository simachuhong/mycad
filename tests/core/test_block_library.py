# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Portable block assets retain only resources required by their definitions."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad.core.block_library import AssetMetadata, capture_block_asset
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.drawing_blocks import BlockDefinition
from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
from mycad.core.sketch import LineEntity
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable


def test_capture_unplaced_and_text_only_definition() -> None:
    text = DrawingText(uuid4().hex, "文字", (1, 2), style_id="s", layer_name="Ink")
    definition = BlockDefinition(uuid4().hex, "原名", (), (text,))
    styles = TextStyleTable(
        (
            TextStyle(),
            TextStyle(style_id="s", name="正文", font_file="/tmp/fonts/a.ttf"),
            TextStyle(style_id="unused", name="不用"),
        ),
        "unused",
    )
    layers = SketchLayerTable((SketchLayer("0"), SketchLayer("Ink"), SketchLayer("unused")))
    snapshot = DrawingCollectionSnapshot(
        (),
        (),
        (),
        styles,
        DimensionStyleTable((DimensionStyle("标准"),), "标准"),
        (),
        (),
        (),
        (),
        layers,
        "0",
        (),
        (),
        (definition,),
        (),
    )
    asset = capture_block_asset(
        snapshot,
        definition.definition_id,
        AssetMetadata("库块", "说明", ("标签",)),
        asset_id=uuid4().hex,
    )
    assert asset.definition == replace(definition, name="库块")
    assert [item.style_id for item in asset.text_styles.styles] == ["s"]
    assert asset.text_styles.current_id == "s"
    assert asset.text_styles.get("s").font_file == "a.ttf"
    assert [layer.name for layer in asset.layers.layers] == ["0", "Ink"]
    assert snapshot.block_definitions == (definition,) and snapshot.text_styles == styles


def test_capture_geometry_only_does_not_require_source_current_style() -> None:
    definition = BlockDefinition(
        uuid4().hex, "line", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    styles = TextStyleTable((TextStyle(style_id="other", name="Other"),), "other")
    snapshot = DrawingCollectionSnapshot(
        (),
        (),
        (),
        styles,
        DimensionStyleTable((DimensionStyle("标准"),), "标准"),
        (),
        (),
        (),
        (),
        SketchLayerTable(),
        "0",
        (),
        (),
        (definition,),
        (),
    )
    asset = capture_block_asset(
        snapshot, definition.definition_id, AssetMetadata("line", "", ()), asset_id=uuid4().hex
    )
    assert asset.text_styles == TextStyleTable()
    with pytest.raises(ValueError):
        capture_block_asset(
            snapshot, uuid4().hex, AssetMetadata("line", "", ()), asset_id=uuid4().hex
        )


def test_asset_rejects_oversized_members_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    import mycad.core.block_library as library

    definition = BlockDefinition(
        uuid4().hex,
        "B",
        (LineEntity(uuid4().hex, (0, 0), (1, 0)),),
        (DrawingText(uuid4().hex, "中文", (0, 0)),),
    )
    styles = TextStyleTable()
    layers = SketchLayerTable()
    monkeypatch.setattr(library, "MAX_MEMBERS", 1)
    with pytest.raises(ValueError, match="成员数量"):
        library.BlockAsset(uuid4().hex, "B", "", (), definition, styles, layers)
    monkeypatch.setattr(library, "MAX_MEMBERS", 2)
    monkeypatch.setattr(library, "MAX_TEXT_BYTES", 5)
    with pytest.raises(ValueError, match="文字内容"):
        library.BlockAsset(uuid4().hex, "B", "", (), definition, styles, layers)


def test_asset_rejects_oversized_curve_points(monkeypatch: pytest.MonkeyPatch) -> None:
    import mycad.core.block_library as library
    from mycad.core.sketch import PolylineEntity

    line = PolylineEntity(uuid4().hex, ((0, 0), (1, 0), (2, 0)))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    monkeypatch.setattr(library, "MAX_CURVE_POINTS", 2)
    with pytest.raises(ValueError, match="曲线点"):
        library.BlockAsset(
            uuid4().hex, "B", "", (), definition, TextStyleTable(), SketchLayerTable()
        )
