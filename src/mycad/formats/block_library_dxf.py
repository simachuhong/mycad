# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Convert supported native DXF block definitions to portable block assets."""

import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

from mycad.core.block_library import AssetMetadata, BlockAsset, capture_block_asset
from mycad.core.block_library_import import AssetIssue
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.drawing_blocks import BlockInstance, make_block_definition
from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
from mycad.core.drawing_text import TextStyleTable
from mycad.core.sketch import Point2D
from mycad.formats.dxf_preview import DxfOutputPreview, prepare_dxf_bytes_preview
from mycad.formats.providers.dxf_provider import (
    DxfExchangeReport,
    read_sketch_dxf,
    write_sketches_dxf,
)


def read_dxf_block_assets(
    path: Path, *, unit_override: str | None = None
) -> tuple[tuple[BlockAsset, ...], tuple[AssetIssue, ...]]:
    """Read named, supported definitions, including those without INSERT instances."""
    imported = read_sketch_dxf(
        path, unit_override=unit_override, include_nested_referenced_blocks=True
    )
    styles = imported.text_styles or TextStyleTable()
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
        imported.sketch.layers,
        "0",
        (),
        (),
        imported.block_definitions,
        (),
    )
    assets = tuple(
        capture_block_asset(
            snapshot,
            definition.definition_id,
            AssetMetadata(definition.name, "", ()),
            asset_id=uuid4().hex,
        )
        for definition in imported.block_definitions
    )
    issues = tuple(AssetIssue("dxf_warning", warning) for warning in imported.report.warnings)
    return assets, issues


def write_block_asset_dxf(asset: BlockAsset, path: Path) -> DxfExchangeReport:
    """Export one definition and an origin placement as real DXF bytes."""
    instance = BlockInstance(uuid4().hex, asset.definition.definition_id, (0, 0))
    return write_sketches_dxf(
        (),
        path,
        drawing_layers=asset.layers,
        text_styles=asset.text_styles,
        block_definitions=(asset.definition,),
        block_instances=(instance,),
    )


def prepare_block_asset_dxf_preview(asset: BlockAsset) -> DxfOutputPreview:
    """Freeze and render actual DXF output bytes before a user writes a file."""
    with tempfile.TemporaryDirectory(prefix="mycad-block-dxf-") as directory:
        path = Path(directory) / "block.dxf"
        report = write_block_asset_dxf(asset, path)
        return prepare_dxf_bytes_preview(path.read_bytes(), report)


class _RawEntity(Protocol):
    def dxftype(self) -> str: ...


class _RawDrawing(Protocol):
    def modelspace(self) -> Iterable[_RawEntity]: ...


def read_dxf_modelspace_asset(
    path: Path, *, name: str, base_mm: Point2D, unit_override: str | None = None
) -> BlockAsset:
    """Convert all supported modelspace geometry/text using an explicit mm base point."""
    import ezdxf.filemanagement as filemanagement

    read = cast("Callable[[Path], _RawDrawing]", vars(filemanagement)["readfile"])
    raw = read(path)
    allowed = {
        "POINT",
        "LINE",
        "LWPOLYLINE",
        "POLYLINE",
        "CIRCLE",
        "ARC",
        "ELLIPSE",
        "SPLINE",
        "TEXT",
        "MTEXT",
    }
    entities = tuple(raw.modelspace())
    unsupported = sorted({item.dxftype() for item in entities if item.dxftype() not in allowed})
    if unsupported:
        raise ValueError(f"模型空间包含不支持的对象：{', '.join(unsupported)}。")
    imported = read_sketch_dxf(path, unit_override=unit_override)
    losses = tuple(
        warning for warning in imported.report.warnings if not warning.startswith("块定义 ")
    )
    if (
        losses
        or imported.sketch.constraints
        or imported.tolerance_frames
        or imported.datum_identifiers
        or imported.detached_dimensions
        or imported.block_instances
    ):
        raise ValueError("模型空间包含无法完整导入的内容：" + "；".join(losses))
    if len(imported.sketch.entities) + len(imported.texts) != len(entities):
        raise ValueError("模型空间有对象未能完整导入，不能创建块。")
    definition = make_block_definition(
        uuid4().hex,
        name,
        tuple((item, imported.sketch.frame) for item in imported.sketch.entities),
        imported.texts,
        base_mm,
    )
    snapshot = DrawingCollectionSnapshot(
        (),
        (),
        (),
        imported.text_styles or TextStyleTable(),
        DimensionStyleTable((DimensionStyle("标准"),), "标准"),
        (),
        (),
        (),
        (),
        imported.sketch.layers,
        "0",
        (),
        (),
        (definition,),
        (),
    )
    return capture_block_asset(
        snapshot, definition.definition_id, AssetMetadata(name, "", ()), asset_id=uuid4().hex
    )
