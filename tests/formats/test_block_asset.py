# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Native block files validate their dependencies and preserve geometry."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from mycad.core.block_library import AssetMetadata, capture_block_asset
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.drawing_blocks import BlockDefinition
from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
from mycad.core.drawing_text import DrawingText, TextStyleTable
from mycad.core.sketch import PolylineEntity
from mycad.core.sketch_layers import SketchLayerTable
from mycad.formats.block_asset import decode_block_asset, encode_block_asset


def asset_sample():
    points = tuple(uuid4().hex for _ in range(3))
    geometry = PolylineEntity(uuid4().hex, ((0, 0), (1, 0), (1, 1)), point_ids=points)
    text = DrawingText(uuid4().hex, "你好", (1, 2))
    definition = BlockDefinition(uuid4().hex, "样例", (geometry,), (text,))
    snapshot = DrawingCollectionSnapshot(
        (),
        (),
        (),
        TextStyleTable(),
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
    return capture_block_asset(
        snapshot, definition.definition_id, AssetMetadata("样例", "", ()), asset_id=uuid4().hex
    )


def test_asset_roundtrip_and_invalid_input() -> None:
    asset = asset_sample()
    encoded = encode_block_asset(asset)
    assert decode_block_asset(encoded) == asset
    record = json.loads(encoded)
    for key, value in (("version", 2), ("content_sha256", "0" * 64), ("units", "inch")):
        with pytest.raises(ValueError):
            decode_block_asset(json.dumps({**record, key: value}).encode())
    with pytest.raises(ValueError):
        decode_block_asset(b'{"format":"mycad.block","format":"mycad.block"}')
    with pytest.raises(ValueError):
        decode_block_asset(b'{"a":NaN}')
    with pytest.raises(ValueError):
        decode_block_asset(b" " * (16 * 1024 * 1024 + 1))
    with pytest.raises(ValueError):
        decode_block_asset(("[" * 33 + "]" * 33).encode())
    changed = replace(asset, description="different description")
    assert changed.content_sha256 == asset.content_sha256


def test_rejects_missing_resources_and_duplicate_member_identity() -> None:
    record = json.loads(encode_block_asset(asset_sample()))
    missing_style = dict(record)
    missing_style["text_styles"] = {
        "styles": [{"style_id": "other", "name": "other"}],
        "current_id": "other",
    }
    with pytest.raises(ValueError, match="资源缺失"):
        decode_block_asset(json.dumps(missing_style, ensure_ascii=False).encode())
    definition = dict(record["definition"])
    definition["entities"] = definition["entities"] * 2
    with pytest.raises(ValueError, match="duplicate"):
        decode_block_asset(
            json.dumps({**record, "definition": definition}, ensure_ascii=False).encode()
        )


def test_parser_counts_nesting_outside_quoted_strings() -> None:
    asset = replace(asset_sample(), description='[{"}\\' * 10)
    assert decode_block_asset(encode_block_asset(asset)) == asset
