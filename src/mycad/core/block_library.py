# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Portable, immutable block assets independent of drawing documents."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import cast
from uuid import UUID

from mycad.core.drawing_blocks import BlockDefinition
from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
from mycad.core.drawing_text import TextStyleTable
from mycad.core.sketch import PolylineEntity, SplineEntity
from mycad.core.sketch_layers import DEFAULT_SKETCH_LAYER, SketchLayerTable

MAX_MEMBERS = 50_000
MAX_CURVE_POINTS = 500_000
MAX_TEXT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AssetMetadata:
    name: str
    description: str
    tags: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(cast("object", self.name), str)
            or not self.name.strip()
            or self.name != self.name.strip()
        ):
            raise ValueError("块名称不能为空或包含首尾空格。")
        if not isinstance(cast("object", self.description), str) or len(self.description) > 4096:
            raise ValueError("块说明不能超过 4096 个字符。")
        if not isinstance(cast("object", self.tags), tuple | list):
            raise ValueError("块标签必须是列表。")
        tags = tuple(self.tags)
        if len(tags) > 32 or any(
            not isinstance(cast("object", tag), str) or not tag.strip() or len(tag) > 64
            for tag in tags
        ):
            raise ValueError("块标签数量或长度超出限制。")
        object.__setattr__(self, "tags", tags)


@dataclass(frozen=True, slots=True)
class BlockAsset:
    asset_id: str
    name: str
    description: str
    tags: tuple[str, ...]
    definition: BlockDefinition
    text_styles: TextStyleTable
    layers: SketchLayerTable

    def __post_init__(self) -> None:
        try:
            if UUID(self.asset_id).hex != self.asset_id:
                raise ValueError("asset_id must be a hex UUID")
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("块库资产身份无效。") from exc
        metadata = AssetMetadata(self.name, self.description, self.tags)
        object.__setattr__(self, "tags", metadata.tags)
        if (
            not isinstance(cast("object", self.definition), BlockDefinition)
            or self.definition.name != self.name
        ):
            raise ValueError("块名称与定义不一致。")
        if not isinstance(cast("object", self.text_styles), TextStyleTable) or not isinstance(
            cast("object", self.layers), SketchLayerTable
        ):
            raise ValueError("块资源表无效。")
        members = (*self.definition.entities, *self.definition.texts)
        if len(members) > MAX_MEMBERS:
            raise ValueError("块成员数量超出限制。")
        points = sum(
            len(item.points_mm) if isinstance(item, PolylineEntity) else len(item.control_points_mm)
            for item in self.definition.entities
            if isinstance(item, PolylineEntity | SplineEntity)
        )
        if points > MAX_CURVE_POINTS:
            raise ValueError("块曲线点数量超出限制。")
        if sum(len(item.text.encode("utf-8")) for item in self.definition.texts) > MAX_TEXT_BYTES:
            raise ValueError("块文字内容超出限制。")
        try:
            for item in members:
                self.layers.get(item.layer_name)
            for item in self.definition.texts:
                self.text_styles.get(item.style_id)
        except KeyError as exc:
            raise ValueError(f"块资源缺失：{exc}") from exc
        for style in self.text_styles.styles:
            if style.font_file and ("/" in style.font_file or "\\" in style.font_file):
                raise ValueError("字体文件必须使用文件名，不能使用路径。")

    @property
    def content_sha256(self) -> str:
        return block_asset_digest(self)


def block_asset_digest(asset: BlockAsset) -> str:
    """Hash canonical typed content, excluding non-content descriptive metadata."""
    content = {
        "units": "mm",
        "definition": asset.definition.to_mapping(),
        "text_styles": asset.text_styles.to_mapping(),
        "layers": asset.layers.to_mapping(),
    }
    encoded = json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def capture_block_asset(
    snapshot: DrawingCollectionSnapshot,
    definition_id: str,
    metadata: AssetMetadata,
    *,
    asset_id: str,
) -> BlockAsset:
    """Capture a definition, including those with no instance, without mutating the drawing."""
    definition = next(
        (item for item in snapshot.block_definitions if item.definition_id == definition_id), None
    )
    if definition is None:
        raise ValueError("块定义不存在。")
    style_ids = {item.style_id for item in definition.texts}
    styles = tuple(
        replace(style, font_file=PurePosixPath(style.font_file.replace("\\", "/")).name)
        if style.font_file
        else style
        for style in snapshot.text_styles.styles
        if style.style_id in style_ids
    )
    if len(styles) != len(style_ids):
        raise ValueError("块文字样式缺失。")
    style_table = TextStyleTable(styles, styles[0].style_id) if styles else TextStyleTable()
    layer_names = {item.layer_name.casefold() for item in (*definition.entities, *definition.texts)}
    layers = [DEFAULT_SKETCH_LAYER]
    try:
        for name in sorted(layer_names - {"0"}):
            layers.append(snapshot.layers.get(name))
    except KeyError as exc:
        raise ValueError(f"块图层缺失：{exc}") from exc
    return BlockAsset(
        asset_id,
        metadata.name,
        metadata.description,
        metadata.tags,
        replace(definition, name=metadata.name),
        style_table,
        SketchLayerTable(tuple(layers)),
    )
