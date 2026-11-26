# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Native DXF blocks can enter a portable block library and leave it again."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol, cast

import ezdxf.filemanagement as filemanagement
import pytest

from mycad.core.sketch import LineEntity
from mycad.formats.block_library_dxf import read_dxf_block_assets, write_block_asset_dxf
from mycad.formats.providers.dxf_provider import DxfUnitOverrideRequired, read_sketch_dxf


class _DxfAttributes(Protocol):
    name: str


class _Entity(Protocol):
    dxf: _DxfAttributes


class _Block(Protocol):
    def __iter__(self) -> Iterator[_Entity]: ...
    def add_line(self, start: tuple[float, float], end: tuple[float, float]) -> object: ...
    def add_circle(self, center: tuple[float, float], radius: float) -> object: ...
    def add_text(self, text: str) -> object: ...
    def add_blockref(self, name: str, point: tuple[float, float]) -> object: ...


class _Blocks(Protocol):
    def new(self, name: str, base_point: tuple[float, float, float] = (0, 0, 0)) -> _Block: ...
    def get(self, name: str) -> _Block: ...


class _Document(Protocol):
    header: dict[str, int]
    blocks: _Blocks

    def modelspace(self) -> _Block: ...
    def saveas(self, path: Path) -> None: ...


new_dxf = cast("Callable[[str], _Document]", vars(filemanagement)["new"])


def test_unreferenced_block_roundtrip_with_basepoint_and_units(tmp_path: Path) -> None:
    document = new_dxf("R2010")
    document.header["$INSUNITS"] = 1
    block = document.blocks.new("BRACKET", base_point=(2, 3, 0))
    block.add_line((2, 3), (3, 3))
    source = tmp_path / "source.dxf"
    document.saveas(source)
    assets, issues = read_dxf_block_assets(source)
    assert not issues and len(assets) == 1
    line = assets[0].definition.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == (0, 0) and line.end_mm == pytest.approx((25.4, 0))
    target = tmp_path / "output.dxf"
    report = write_block_asset_dxf(assets[0], target)
    assert report.dxf_version == "AC1024"
    restored = read_sketch_dxf(target)
    assert len(restored.block_definitions) == len(restored.block_instances) == 1
    restored_line = restored.block_definitions[0].entities[0]
    assert isinstance(restored_line, LineEntity)
    assert restored_line.end_mm == pytest.approx((25.4, 0))
    assert restored.block_instances[0].insertion_mm == (0, 0)


def test_unknown_units_require_explicit_override(tmp_path: Path) -> None:
    document = new_dxf("R2010")
    document.header["$INSUNITS"] = 0
    document.blocks.new("SIMPLE").add_circle((0, 0), 3)
    path = tmp_path / "unknown.dxf"
    document.saveas(path)
    with pytest.raises(DxfUnitOverrideRequired):
        read_dxf_block_assets(path)
    assets, _issues = read_dxf_block_assets(path, unit_override="mm")
    assert len(assets) == 1


def test_nested_block_rejected_but_its_supported_child_available(tmp_path: Path) -> None:
    document = new_dxf("R2010")
    document.header["$INSUNITS"] = 4
    document.blocks.new("CHILD").add_line((0, 0), (2, 0))
    document.blocks.new("NESTED").add_blockref("CHILD", (0, 0))
    path = tmp_path / "nested.dxf"
    document.saveas(path)
    assets, issues = read_dxf_block_assets(path)
    assert [asset.name for asset in assets] == ["CHILD"]
    assert any("NESTED" in issue.message for issue in issues)


def test_preview_is_rendered_from_exact_export_bytes(tmp_path: Path) -> None:
    from mycad.formats.block_library_dxf import prepare_block_asset_dxf_preview

    document = new_dxf("R2010")
    document.header["$INSUNITS"] = 4
    document.blocks.new("B").add_line((0, 0), (2, 1))
    source = tmp_path / "source.dxf"
    document.saveas(source)
    assets, _issues = read_dxf_block_assets(source)
    preview = prepare_block_asset_dxf_preview(assets[0])
    assert b"<svg" in preview.svg_bytes
    destination = tmp_path / "previewed.dxf"
    preview.write(destination)
    assert destination.read_bytes() == preview.dxf_bytes
    assert len(read_sketch_dxf(destination).block_instances) == 1


def test_modelspace_can_be_saved_as_block_with_explicit_base(tmp_path: Path) -> None:
    from mycad.formats.block_library_dxf import read_dxf_modelspace_asset

    document = new_dxf("R2010")
    document.header["$INSUNITS"] = 1
    document.modelspace().add_line((2, 3), (3, 3))
    path = tmp_path / "geometry.dxf"
    document.saveas(path)
    asset = read_dxf_modelspace_asset(path, name="Model", base_mm=(50.8, 76.2))
    line = asset.definition.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == pytest.approx((0, 0))
    assert line.end_mm == pytest.approx((25.4, 0))


def test_modelspace_refuses_inserts_and_unsupported_objects(tmp_path: Path) -> None:
    from mycad.formats.block_library_dxf import read_dxf_modelspace_asset

    document = new_dxf("R2010")
    document.header["$INSUNITS"] = 4
    document.blocks.new("B").add_line((0, 0), (1, 0))
    document.modelspace().add_blockref("B", (0, 0))
    path = tmp_path / "contains-insert.dxf"
    document.saveas(path)
    with pytest.raises(ValueError, match="INSERT"):
        read_dxf_modelspace_asset(path, name="No", base_mm=(0, 0))


def test_text_only_block_and_unsupported_block_report(tmp_path: Path) -> None:
    document = new_dxf("R2010")
    document.header["$INSUNITS"] = 4
    document.blocks.new("TEXT_ONLY").add_text("LABEL")
    document.blocks.new("BAD").add_blockref("TEXT_ONLY", (0, 0))
    path = tmp_path / "text.dxf"
    document.saveas(path)
    assets, issues = read_dxf_block_assets(path)
    assert len(assets) == 1 and assets[0].name == "TEXT_ONLY"
    assert not assets[0].definition.entities and assets[0].definition.texts[0].text == "LABEL"
    assert any("BAD" in issue.message for issue in issues)
    result = tmp_path / "text-output.dxf"
    write_block_asset_dxf(assets[0], result)
    imported = read_sketch_dxf(result)
    assert imported.block_definitions[0].texts[0].text == "LABEL"


def test_datum_helper_blocks_are_not_offered_as_library_assets(tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    path = tmp_path / "datum.dxf"
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (16, 0), layout_mode="shared")
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    read = cast("Callable[[Path], _Document]", vars(filemanagement)["readfile"])
    document = read(path)
    document.blocks.new("DATUM_HELPER").add_line((0, 0), (1, 0))
    document.blocks.new("USER_BLOCK").add_line((0, 0), (2, 0))
    # The application's native datum definition is an INSERT in modelspace.
    datum_insert = next(iter(document.modelspace()))
    datum_name = str(datum_insert.dxf.name)
    document.blocks.get(datum_name).add_blockref("DATUM_HELPER", (0, 0))
    document.saveas(path)
    assets, _issues = read_dxf_block_assets(path)
    assert [asset.name for asset in assets] == ["USER_BLOCK"]
