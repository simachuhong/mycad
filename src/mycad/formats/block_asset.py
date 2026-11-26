# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Strict, versioned JSON encoding for portable 2D block assets."""

from __future__ import annotations

import hmac
import json
from typing import cast

from mycad.core.block_library import BlockAsset
from mycad.core.drawing_blocks import BlockDefinition
from mycad.core.drawing_text import TextStyleTable
from mycad.core.sketch_layers import SketchLayerTable

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 32


def encode_block_asset(asset: BlockAsset) -> bytes:
    record = {
        "format": "mycad.block",
        "version": 1,
        "units": "mm",
        "asset_id": asset.asset_id,
        "name": asset.name,
        "description": asset.description,
        "tags": list(asset.tags),
        "definition": asset.definition.to_mapping(),
        "text_styles": asset.text_styles.to_mapping(),
        "layers": asset.layers.to_mapping(),
        "content_sha256": asset.content_sha256,
    }
    data = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("块文件超过大小限制。")
    return data


def _check_depth(text: str) -> None:
    depth = 0
    quoted = False
    escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("块文件嵌套层次超出限制。")
        elif char in "]}":
            depth -= 1


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    record: dict[str, object] = {}
    for key, value in pairs:
        if key in record:
            raise ValueError(f"块文件字段重复：{key}")
        record[key] = value
    return record


def _reject_constant(value: str) -> None:
    raise ValueError(f"块文件包含无效数字：{value}")


def decode_block_asset(data: bytes) -> BlockAsset:
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("块文件超过大小限制。")
    try:
        text = data.decode("utf-8")
        _check_depth(text)
        record = json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
        if not isinstance(record, dict):
            raise ValueError("块文件必须是对象。")
        values = cast("dict[str, object]", record)
        if set(values) != {
            "format",
            "version",
            "units",
            "asset_id",
            "name",
            "description",
            "tags",
            "definition",
            "text_styles",
            "layers",
            "content_sha256",
        }:
            raise ValueError("块文件字段缺失或未知。")
        if (
            values["format"] != "mycad.block"
            or type(values["version"]) is not int
            or values["version"] != 1
        ):
            raise ValueError("不支持的块文件格式或版本。")
        if values["units"] != "mm" or not isinstance(values["tags"], list):
            raise ValueError("块文件单位或标签无效。")
        asset = BlockAsset(
            cast("str", values["asset_id"]),
            cast("str", values["name"]),
            cast("str", values["description"]),
            tuple(cast("list[str]", values["tags"])),
            BlockDefinition.from_mapping(values["definition"]),
            TextStyleTable.from_mapping(values["text_styles"]),
            SketchLayerTable.from_mapping(values["layers"]),
        )
        digest = values["content_sha256"]
        if not isinstance(digest, str) or not hmac.compare_digest(digest, asset.content_sha256):
            raise ValueError("块文件内容校验失败。")
        return asset
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError, TypeError) as exc:
        raise ValueError(f"无法读取块文件：{exc}") from exc
