# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Build disposable external-block-library acceptance examples in a new directory."""

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import ezdxf.filemanagement as filemanagement

from mycad.core.block_library import BlockAsset
from mycad.core.drawing_blocks import BlockDefinition
from mycad.core.drawing_text import DrawingText, TextStyleTable
from mycad.core.sketch import LineEntity
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.formats.block_asset import encode_block_asset


class _Block(Protocol):
    def add_line(self, start: tuple[float, float], end: tuple[float, float]) -> object: ...
    def add_blockref(self, name: str, point: tuple[float, float]) -> object: ...


class _Blocks(Protocol):
    def new(self, name: str) -> _Block: ...


class _Document(Protocol):
    header: dict[str, int]
    blocks: _Blocks

    def saveas(self, path: Path) -> None: ...


def generate(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    layers = SketchLayerTable((SketchLayer("0"), SketchLayer("示例层")))

    def write(folder: str, name: str, length: float, *, text_only: bool = False) -> None:
        entities = (
            ()
            if text_only
            else (LineEntity(uuid4().hex, (0, 0), (length, 0), layer_name="示例层"),)
        )
        texts = (DrawingText(uuid4().hex, "中文示例", (0, 2), layer_name="示例层"),)
        definition = BlockDefinition(uuid4().hex, name, entities, texts)
        asset = BlockAsset(uuid4().hex, name, "验收样例", (), definition, TextStyleTable(), layers)
        path = destination / folder
        path.mkdir(exist_ok=True)
        (path / f"{uuid4().hex}.myblock").write_bytes(encode_block_asset(asset))

    write("几何文字", "含中文及图层", 30)
    write("纯文字", "纯文字", 0, text_only=True)
    write("同名一", "同名不同内容", 10)
    write("同名二", "同名不同内容", 20)
    (destination / "损坏样例.myblock").write_bytes(b'{"format": "broken"')
    new_document = cast("Callable[[str], _Document]", vars(filemanagement)["new"])
    document = new_document("R2010")
    document.header["$INSUNITS"] = 4
    document.blocks.new("CHILD").add_line((0, 0), (10, 0))
    document.blocks.new("NESTED").add_blockref("CHILD", (0, 0))
    document.saveas(destination / "不支持嵌套.dxf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="将创建的全新目录")
    generate(parser.parse_args().destination)
