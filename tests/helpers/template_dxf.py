# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed boundary for ezdxf fixture authoring APIs with incomplete annotations."""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

from ezdxf.filemanagement import new

from mycad.core.drawing_projection import Point2


class Insert(Protocol):
    def add_auto_attribs(self, values: dict[str, str]) -> object: ...


class Layout(Protocol):
    def add_line(self, start: Point2, end: Point2) -> object: ...
    def add_point(self, location: Point2) -> object: ...
    def add_attdef(
        self,
        tag: str,
        insert: Point2,
        *,
        height: float,
        text: str = "",
        dxfattribs: Mapping[str, object] | None = None,
    ) -> object: ...
    def add_polyline2d(
        self, points: list[Point2], *, dxfattribs: Mapping[str, object]
    ) -> object: ...
    def add_text(self, text: str, *, dxfattribs: Mapping[str, object]) -> object: ...
    def add_mtext(self, text: str, *, dxfattribs: Mapping[str, object]) -> object: ...
    def add_blockref(
        self, name: str, insert: Point2, *, dxfattribs: Mapping[str, object] | None = None
    ) -> Insert: ...
    def add_lwpolyline(self, points: list[Point2]) -> object: ...
    def add_circle(self, center: Point2, radius: float) -> object: ...


class Blocks(Protocol):
    def new(self, name: str) -> Layout: ...


class Layouts(Protocol):
    def get(self, name: str) -> Layout: ...


class Drawing(Protocol):
    blocks: Blocks
    layouts: Layouts

    def modelspace(self) -> Layout: ...
    def saveas(self, path: Path) -> None: ...


class NewDrawing(Protocol):
    def __call__(self, version: str = "R2010", *, units: int = 4) -> Drawing: ...


def new_dxf(version: str = "R2010", *, units: int = 4) -> Drawing:
    return cast("NewDrawing", new)(version, units=units)
