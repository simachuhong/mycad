# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicit static engineering DXF export; separate from the sketch provider."""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol, cast

from ezdxf.filemanagement import new as _new_dxf

from mycad.core.drawing_paper import paper_texts, sheet_frame, validate_drawing_output
from mycad.core.drawing_projection import (
    ArcCurve,
    CurveGeometry,
    DrawingScene,
    EllipseCurve,
    LineCurve,
    Point2,
)


class _Table(Protocol):
    def new(self, name: str, *, dxfattribs: Mapping[str, object]) -> object: ...


class _Linetype(Protocol):
    def setup_pattern(self, pattern: Sequence[float]) -> None: ...


class _Layout(Protocol):
    def add_line(
        self, start: Point2, end: Point2, *, dxfattribs: Mapping[str, object]
    ) -> object: ...
    def add_circle(
        self, center: Point2, radius: float, *, dxfattribs: Mapping[str, object]
    ) -> object: ...
    def add_arc(
        self,
        center: Point2,
        radius: float,
        start_angle: float,
        end_angle: float,
        *,
        dxfattribs: Mapping[str, object],
    ) -> object: ...
    def add_ellipse(
        self,
        center: Point2,
        major_axis: Point2,
        ratio: float,
        start_param: float,
        end_param: float,
        *,
        dxfattribs: Mapping[str, object],
    ) -> object: ...
    def add_rational_spline(
        self,
        control_points: tuple[tuple[float, float, float], ...],
        weights: tuple[float, ...],
        degree: int,
        knots: tuple[float, ...],
        *,
        dxfattribs: Mapping[str, object],
    ) -> object: ...
    def add_blockref(
        self, name: str, insert: Point2, *, dxfattribs: Mapping[str, object]
    ) -> object: ...
    def add_mtext(self, text: str, *, dxfattribs: Mapping[str, object]) -> object: ...
    def page_setup(
        self,
        *,
        size: Point2,
        margins: tuple[float, float, float, float],
        units: str,
        scale: tuple[int, int],
    ) -> None: ...


class _Blocks(Protocol):
    def new(self, name: str) -> _Layout: ...


class _Layouts(Protocol):
    def get(self, name: str) -> _Layout: ...
    def rename(self, old_name: str, new_name: str) -> None: ...


class _Drawing(Protocol):
    header: MutableMapping[str, object]
    layers: _Table
    styles: _Table
    linetypes: _Table
    blocks: _Blocks
    layouts: _Layouts

    def saveas(self, path: Path) -> None: ...


class _NewDxf(Protocol):
    def __call__(self, dxfversion: str, *, units: int) -> _Drawing: ...


def atomic_drawing_output(target: Path, write: Callable[[Path], None]) -> None:
    """Only replace the chosen file after the complete writer succeeds."""
    with NamedTemporaryFile(
        prefix=f".{target.stem}-", suffix=target.suffix, dir=target.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        write(temporary)
        if temporary.stat().st_size == 0:
            raise ValueError("出图结果为空，原文件未修改")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _curve(layout: _Layout, geometry: CurveGeometry, layer: str, *, scale: float = 1) -> None:
    attributes: dict[str, object] = {"layer": layer, "ltscale": 1 / scale}
    if isinstance(geometry, LineCurve):
        layout.add_line(geometry.start, geometry.end, dxfattribs=attributes)
    elif isinstance(geometry, ArcCurve):
        if abs(geometry.sweep_deg) >= 360 - 1e-8:
            layout.add_circle(geometry.center, geometry.radius, dxfattribs=attributes)
        else:
            start, end = geometry.start_deg, geometry.start_deg + geometry.sweep_deg
            if geometry.sweep_deg < 0:
                start, end = end, start
            layout.add_arc(
                geometry.center, geometry.radius, start % 360, end % 360, dxfattribs=attributes
            )
    elif isinstance(geometry, EllipseCurve):
        angle = math.radians(geometry.rotation_deg)
        start, end = (
            math.radians(geometry.start_deg),
            math.radians(geometry.start_deg + geometry.sweep_deg),
        )
        if geometry.sweep_deg < 0:
            start, end = end, start
        if abs(geometry.sweep_deg) >= 360 - 1e-8:
            start, end = 0, 2 * math.pi
        else:
            start, end = start % (2 * math.pi), end % (2 * math.pi)
        layout.add_ellipse(
            geometry.center,
            (geometry.major_radius * math.cos(angle), geometry.major_radius * math.sin(angle)),
            geometry.minor_radius / geometry.major_radius,
            start,
            end,
            dxfattribs=attributes,
        )
    else:
        if geometry.periodic:
            raise ValueError("周期样条需要先规范化为非周期精确曲线")
        knots = tuple(
            k
            for k, count in zip(geometry.knots, geometry.multiplicities, strict=True)
            for _ in range(count)
        )
        layout.add_rational_spline(
            tuple((x, y, 0) for x, y in geometry.poles),
            geometry.weights,
            geometry.degree,
            knots,
            dxfattribs=attributes,
        )


def export_drawing_dxf(scene: DrawingScene, target: Path) -> None:
    validate_drawing_output(scene)
    document = cast("_NewDxf", _new_dxf)("R2010", units=4)
    for name, pattern in (
        ("MYCAD_HIDDEN", (4, 2.5, -1.5)),
        ("MYCAD_TANGENT", (2, 0.1, -1.9)),
        ("MYCAD_CENTER", (8, 5, -1, 1, -1)),
    ):
        definition = cast(
            "_Linetype", document.linetypes.new(name, dxfattribs={"description": name})
        )
        definition.setup_pattern(pattern)
    for name, weight, line_type in (
        ("VISIBLE", 25, "CONTINUOUS"),
        ("HIDDEN", 18, "MYCAD_HIDDEN"),
        ("TANGENT", 18, "MYCAD_TANGENT"),
        ("CENTER", 18, "MYCAD_CENTER"),
        ("DIM", 18, "CONTINUOUS"),
        ("FRAME", 30, "CONTINUOUS"),
    ):
        color = 0x087589 if name == "DIM" else 0x687789 if name == "HIDDEN" else 0x26313C
        document.layers.new(
            name,
            dxfattribs={
                "color": 7,
                "true_color": color,
                "lineweight": weight,
                "linetype": line_type,
            },
        )
    document.styles.new("MyCAD", dxfattribs={"font": "NotoSansCJK-Regular.ttc"})
    document.header["$INSUNITS"] = 4
    document.header["$LWDISPLAY"] = True
    document.header["$PSLTSCALE"] = 0
    document.layouts.rename("Layout1", "工程图")
    paper = document.layouts.get("工程图")
    paper.page_setup(size=scene.size_mm, margins=(0, 0, 0, 0), units="mm", scale=(1, 1))
    for view in scene.views:
        name = f"VIEW_{view.view_id.hex}"
        block = document.blocks.new(name)
        for curve in view.curves:
            _curve(block, curve.geometry, curve.visibility.upper(), scale=view.scale)
        paper.add_blockref(
            name,
            view.anchor_mm,
            dxfattribs={"xscale": view.scale, "yscale": view.scale, "zscale": view.scale},
        )
    for line in sheet_frame(scene):
        _curve(paper, line, "FRAME")
    for annotation in scene.resolved_annotations:
        for geometry in annotation.curves:
            _curve(paper, geometry, "CENTER" if annotation.kind == "center" else "DIM")
    for text in paper_texts(scene):
        # Escape formatting controls: user text remains literal DXF MTEXT.
        literal = (
            text.text.replace("\\", "\\\\")
            .replace("{", "\\{")
            .replace("}", "\\}")
            .replace("\n", "\\P")
        )
        paper.add_mtext(
            literal,
            dxfattribs={
                "insert": text.position_mm,
                "char_height": text.height_mm,
                "attachment_point": 1,
                "style": "MyCAD",
                "layer": text.layer,
            },
        )
    atomic_drawing_output(target, document.saveas)
