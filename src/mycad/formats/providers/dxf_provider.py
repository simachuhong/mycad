# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exchange the supported neutral sketch subset as 2D DXF R2010."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Iterator, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, cast, runtime_checkable
from uuid import UUID, uuid4

import ezdxf.filemanagement as _filemanagement
import ezdxf.render.arrows as _arrows
from ezdxf.colors import aci2rgb, int2rgb
from ezdxf.entities import Dimension
from ezdxf.filemanagement import new as _new_dxf
from ezdxf.lldxf.const import DXFAttributeError, DXFValueError
from ezdxf.render.arrows import ARROWS

from mycad.core.angular_dimension import angular_sector
from mycad.core.cross_sketch_tangency import (
    project_coplanar_vector,
    project_polyline_entity,
    project_tangent_entity,
)
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.exceptions import ValidationError
from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.ports import ExportableKernel
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    Point2D,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import (
    DEFAULT_SKETCH_LAYER,
    STANDARD_LINEWEIGHTS_MM,
    SketchLayer,
    SketchLayerTable,
    SketchLinetype,
)
from mycad.formats.base import FormatProvider

_APPID = "MYCAD"
_DIMENSION_SNAPSHOT_APPID = "MYCAD_DIMENSION_SNAPSHOT"
_DIMENSION_STYLE_APPID = "MYCAD_DIMENSION_STYLE"
_DIMENSION_SNAPSHOT_FIELDS = (
    "layer",
    "dimstyle",
    "dimtype",
    "text",
    "text_rotation",
    "horizontal_direction",
    "angle",
    "start_angle",
    "end_angle",
    "is_partial",
    "has_leader",
    "leader_point1",
    "leader_point2",
    "extrusion",
    "defpoint",
    "defpoint2",
    "defpoint3",
    "defpoint4",
    "defpoint5",
    "text_midpoint",
)
_DIMENSION_STYLE_FIELDS = (
    "dimdec",
    "dimadec",
    "dimclrt",
    "dimclrd",
    "dimclre",
    "dimtxt",
    "dimasz",
    "dimscale",
    "dimlfac",
    "dimrnd",
    "dimzin",
    "dimazin",
    "dimdsep",
    "dimaunit",
    "dimpost",
    "dimtad",
    "dimgap",
)
_DIMENSION_STYLE_V3_FIELDS = (
    *_DIMENSION_STYLE_FIELDS,
    "dimcen",
    "dimexe",
    "dimexo",
    "dimdle",
    "dimsah",
    "dimblk1",
    "dimblk2",
)
_DIMENSION_STYLE_V4_FIELDS = (*_DIMENSION_STYLE_V3_FIELDS, "dimlwd", "dimlwe")
_DIMENSION_STYLE_V5_FIELDS = (*_DIMENSION_STYLE_V4_FIELDS, "dimltype", "dimltex1", "dimltex2")
_DIMENSION_STYLE_V6_FIELDS = (*_DIMENSION_STYLE_V5_FIELDS, "dimse1", "dimse2")
_DIMENSION_STYLE_V7_FIELDS = (*_DIMENSION_STYLE_V6_FIELDS, "dimsd1", "dimsd2")
_DIMENSION_STYLE_DEFAULTS: dict[str, int | float | str] = {
    "dimclrt": 0,
    "dimclrd": 0,
    "dimclre": 0,
    "dimscale": 1.0,
    "dimrnd": 0.0,
    "dimgap": 0.625,
    "dimcen": 2.5,
    "dimdle": 0.0,
    "dimexe": 1.25,
    "dimexo": 0.625,
    "dimsah": 0,
    "dimblk1": "",
    "dimblk2": "",
    "dimlwd": -2,
    "dimlwe": -2,
    "dimltype": "",
    "dimltex1": "",
    "dimltex2": "",
    "dimse1": 0,
    "dimse2": 0,
    "dimsd1": 0,
    "dimsd2": 0,
}
_CONSTRUCTION_LAYER = "MYCAD_CONSTRUCTION"
_UNIT_TO_MM: dict[str, float] = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "inch": 25.4,
    "ft": 304.8,
    "mil": 0.0254,
    "micron": 0.001,
}
_INSUNITS_TO_NAME = {1: "inch", 2: "ft", 4: "mm", 5: "cm", 6: "m", 9: "mil", 13: "micron"}
_DXF_LINETYPE_NAMES: dict[SketchLinetype, str] = {
    "CONTINUOUS": "CONTINUOUS",
    "DASHED": "MYCAD_DASHED",
    "DOTTED": "MYCAD_DOTTED",
    "DASHDOT": "MYCAD_DASHDOT",
}
_DXF_LINETYPE_VALUES: dict[str, SketchLinetype] = {
    dxf_name: linetype for linetype, dxf_name in _DXF_LINETYPE_NAMES.items()
}
_DXF_LINETYPE_PATTERNS: dict[SketchLinetype, tuple[float, ...]] = {
    "CONTINUOUS": (1.0, 1.0),
    "DASHED": (1.0, 0.65, -0.35),
    "DOTTED": (1.0, 0.0, -1.0),
    "DASHDOT": (1.0, 0.55, -0.2, 0.0, -0.25),
}


@dataclass(frozen=True, slots=True)
class DxfExchangeReport:
    """Visible summary of one subset exchange, including every known omission."""

    action: str
    dxf_version: str
    unit: str
    entity_count: int
    warnings: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """Whether this exchange skipped or approximated no known content."""
        return not self.warnings

    def __str__(self) -> str:
        summary = (
            f"DXF {self.dxf_version}，单位 {self.unit}，{self.action} {self.entity_count} 个图元"
        )
        if not self.warnings:
            return f"{summary}。"
        details = "；".join(self.warnings)
        return f"{summary}；{len(self.warnings)} 条未完整交换提示：{details}。"


class DxfUnitOverrideRequired(ValueError):
    """The DXF omitted a supported linear unit, so scaling needs user input."""


@dataclass(frozen=True, slots=True)
class DxfSketchImport:
    """One imported XY sketch and the report needed before accepting it."""

    sketch: Sketch
    report: DxfExchangeReport
    dimension_styles: tuple[tuple[str, DimensionStyle], ...] = ()


@runtime_checkable
class _SketchSource(Protocol):
    @property
    def sketches(self) -> tuple[Sketch, ...]:
        """Neutral sketches currently replayed into the kernel."""
        ...


@runtime_checkable
class _DimensionStyleSource(Protocol):
    @property
    def drawing_dimension_styles(self) -> DimensionStyleTable: ...


@runtime_checkable
class _ArraySource(Protocol):
    @property
    def associative_arrays(self) -> tuple[object, ...]:
        """Array relationships in the replayed document, if exposed."""
        ...


@runtime_checkable
class _RasterSource(Protocol):
    @property
    def drawing_rasters(self) -> tuple[object, ...]:
        """Embedded images in the replayed document, if exposed."""
        ...


@runtime_checkable
class _CrossTangencySource(Protocol):
    @property
    def cross_sketch_tangencies(self) -> tuple[object, ...]:
        """Cross-sketch relations in the replayed document, if exposed."""
        ...


class _DxfAttributes(Protocol):
    layer: str
    horizontal_direction: float
    location: Sequence[float]
    start: Sequence[float]
    end: Sequence[float]
    center: Sequence[float]
    radius: float
    start_angle: float
    end_angle: float
    extrusion: Sequence[float]
    elevation: object
    handle: str
    insert: Sequence[float]
    name: str
    rotation: float
    xscale: float

    def get(self, name: str, default: object = None) -> object: ...


class _XdataTag(Protocol):
    code: int
    value: object


class _DxfEntity(Protocol):
    dxf: _DxfAttributes

    def dxftype(self) -> str: ...

    def set_xdata(self, appid: str, tags: Iterable[tuple[int, str]]) -> None: ...

    def get_xdata(self, appid: str) -> Sequence[_XdataTag]: ...


class _LwPolyline(_DxfEntity, Protocol):
    closed: bool

    def get_points(self, format: str = "xyseb") -> Iterable[Sequence[float]]: ...


class _Spline(_DxfEntity, Protocol):
    control_points: Sequence[Sequence[float]]
    knots: Sequence[float]
    weights: Sequence[float]


class _Modelspace(Protocol):
    def delete_entity(self, entity: _DxfEntity) -> None: ...

    def add_point(
        self, location: Sequence[float], *, dxfattribs: Mapping[str, object]
    ) -> _DxfEntity: ...

    def add_open_spline(
        self,
        control_points: Iterable[Sequence[float]],
        *,
        degree: int,
        knots: Iterable[float],
        dxfattribs: Mapping[str, object],
    ) -> _DxfEntity: ...

    def __iter__(self) -> Iterator[_DxfEntity]: ...

    def add_line(
        self, start: Sequence[float], end: Sequence[float], *, dxfattribs: Mapping[str, object]
    ) -> _DxfEntity: ...

    def add_lwpolyline(
        self,
        points: Iterable[Sequence[float]],
        *,
        close: bool = False,
        dxfattribs: Mapping[str, object],
    ) -> _DxfEntity: ...

    def add_circle(
        self, center: Sequence[float], radius: float, *, dxfattribs: Mapping[str, object]
    ) -> _DxfEntity: ...

    def add_arc(
        self,
        center: Sequence[float],
        radius: float,
        start_angle: float,
        end_angle: float,
        *,
        dxfattribs: Mapping[str, object],
    ) -> _DxfEntity: ...

    def add_aligned_dim(
        self,
        p1: Sequence[float],
        p2: Sequence[float],
        distance: float,
        *,
        text: str,
        override: Mapping[str, object],
        dxfattribs: Mapping[str, object],
    ) -> _DimensionOverride: ...

    def add_linear_dim(
        self,
        base: Sequence[float],
        p1: Sequence[float],
        p2: Sequence[float],
        *,
        angle: float,
        text: str,
        override: Mapping[str, object],
        dxfattribs: Mapping[str, object],
    ) -> _DimensionOverride: ...

    def add_ordinate_dim(
        self,
        feature_location: Sequence[float],
        offset: Sequence[float],
        dtype: int,
        *,
        origin: Sequence[float],
        text: str,
        override: Mapping[str, object],
        dxfattribs: Mapping[str, object],
    ) -> _DimensionOverride: ...

    def add_arc_dim_3p(
        self,
        base: Sequence[float],
        center: Sequence[float],
        p1: Sequence[float],
        p2: Sequence[float],
        *,
        location: Sequence[float],
        text: str,
        override: Mapping[str, object],
        dxfattribs: Mapping[str, object],
    ) -> _DimensionOverride: ...

    def add_angular_dim_3p(
        self,
        base: Sequence[float],
        center: Sequence[float],
        p1: Sequence[float],
        p2: Sequence[float],
        *,
        location: Sequence[float],
        text: str,
        override: Mapping[str, object],
        dxfattribs: Mapping[str, object],
    ) -> _DimensionOverride: ...

    def add_radius_dim(
        self,
        center: Sequence[float],
        *,
        radius: float,
        angle: float,
        location: Sequence[float],
        text: str,
        override: Mapping[str, object],
        dxfattribs: Mapping[str, object],
    ) -> _DimensionOverride: ...

    def add_diameter_dim(
        self,
        center: Sequence[float],
        *,
        radius: float,
        angle: float,
        location: Sequence[float],
        text: str,
        override: Mapping[str, object],
        dxfattribs: Mapping[str, object],
    ) -> _DimensionOverride: ...


class _DimensionOverride(Protocol):
    dimension: _DxfEntity

    def __setitem__(self, key: str, value: object) -> None: ...

    def commit(self) -> None: ...

    def render(self) -> object: ...

    def set_location(
        self, location: Sequence[float], leader: bool = False, relative: bool = False
    ) -> None: ...


class _NativeDimensionStyle(Protocol):
    def get(self, key: str, default: object = None) -> object: ...


class _NativeDimension(_DxfEntity, Protocol):
    def override(self) -> _NativeDimensionStyle: ...

    def get_geometry_block(self) -> _Modelspace | None: ...


class _ArrowConnection(Protocol):
    def __call__(
        self, name: str, insert: Sequence[float], scale: float, rotation: float
    ) -> Sequence[float]: ...


_arrow_connection = cast("_ArrowConnection", vars(_arrows)["connection_point"])


def _swap_dimension_end_styles(override: dict[str, object]) -> None:
    """Map reference order to the opposite DXF arc endpoint order."""
    for first, second in (
        ("dimse1", "dimse2"),
        ("dimsd1", "dimsd2"),
        ("dimltex1", "dimltex2"),
        ("dimblk1", "dimblk2"),
    ):
        override[first], override[second] = override[second], override[first]
    first_arrow = override.pop("suppress_arrow1", False)
    second_arrow = override.pop("suppress_arrow2", False)
    override["suppress_arrow1"] = second_arrow
    override["suppress_arrow2"] = first_arrow


def _clip_angular_dimension_line(
    dimension: _DxfEntity,
    center: Point2D,
    radius: float,
    start: float,
    sweep: float,
    split: float,
    suppress_start: bool,
    suppress_end: bool,
) -> None:
    """Apply DIMSD to the rendered arc; ezdxf only applies it to straight dimensions."""
    block = cast("_NativeDimension", dimension).get_geometry_block()
    if block is None:
        return
    for entity in tuple(block):
        if entity.dxftype() != "ARC":
            continue
        arc_center = entity.dxf.center
        if math.hypot(
            arc_center[0] - center[0], arc_center[1] - center[1]
        ) > 1e-7 or not math.isclose(entity.dxf.radius, radius, rel_tol=1e-8, abs_tol=1e-7):
            continue
        arc_start = (math.radians(entity.dxf.start_angle) - start) % math.tau
        if arc_start > sweep and math.tau - arc_start < arc_start - sweep:
            arc_start -= math.tau
        arc_end = arc_start + math.radians((entity.dxf.end_angle - entity.dxf.start_angle) % 360.0)
        if suppress_start:
            arc_start = max(arc_start, split)
        if suppress_end:
            arc_end = min(arc_end, split)
        if arc_end - arc_start <= 1e-10:
            block.delete_entity(entity)
        else:
            entity.dxf.start_angle = math.degrees(start + arc_start)
            entity.dxf.end_angle = math.degrees(start + arc_end)


def _clip_radial_dimension_line(
    dimension: _DxfEntity,
    center: Point2D,
    location: Point2D,
    label: Point2D,
    *,
    radius_dimension: bool,
    suppress_first: bool,
    suppress_second: bool,
) -> None:
    """Clip collinear dimension strokes while retaining off-axis leaders."""
    block = cast("_NativeDimension", dimension).get_geometry_block()
    if block is None:
        return
    dx, dy = location[0] - center[0], location[1] - center[1]
    distance = math.hypot(dx, dy)
    if distance <= 1e-10:
        return
    ux, uy = dx / distance, dy / distance
    split = (label[0] - center[0]) * ux + (label[1] - center[1]) * uy
    for entity in tuple(block):
        if entity.dxftype() != "LINE":
            continue
        a, b = entity.dxf.start, entity.dxf.end
        if any(
            abs((point[0] - center[0]) * uy - (point[1] - center[1]) * ux) > 1e-7
            for point in (a, b)
        ):
            continue
        a_t = (a[0] - center[0]) * ux + (a[1] - center[1]) * uy
        b_t = (b[0] - center[0]) * ux + (b[1] - center[1]) * uy
        low, high = sorted((a_t, b_t))
        if radius_dimension and suppress_first:
            block.delete_entity(entity)
            continue
        if suppress_first:
            high = min(high, split)
        if suppress_second:
            low = max(low, split)
        if high - low <= 1e-10:
            block.delete_entity(entity)
        else:
            entity.dxf.start = (center[0] + low * ux, center[1] + low * uy, 0.0)
            entity.dxf.end = (center[0] + high * ux, center[1] + high * uy, 0.0)


def _add_radial_center_mark(
    dimension: _DxfEntity,
    center: Point2D,
    radius: float,
    style: DimensionStyle,
    scale: float,
) -> None:
    block = cast("_NativeDimension", dimension).get_geometry_block()
    if block is None or style.center_mark == "none":
        return
    size = style.center_size * scale
    vectors = ((1.0, 0.0), (0.0, 1.0))
    segments = [
        ((center[0] - x * size, center[1] - y * size), (center[0] + x * size, center[1] + y * size))
        for x, y in vectors
    ]
    if style.center_mark == "line" and radius >= size:
        for x, y in (*vectors, (-1.0, 0.0), (0.0, -1.0)):
            segments.append(
                (
                    (center[0] + 2 * size * x, center[1] + 2 * size * y),
                    (center[0] + (radius + size) * x, center[1] + (radius + size) * y),
                )
            )
    attrs: Mapping[str, object] = {
        "color": style.extension_color,
        "lineweight": style.extension_lineweight,
    }
    for start, end in segments:
        if any(
            entity.dxftype() == "LINE"
            and math.dist(tuple(entity.dxf.start)[:2], start) < 1e-7
            and math.dist(tuple(entity.dxf.end)[:2], end) < 1e-7
            for entity in block
        ):
            continue
        block.add_line(start, end, dxfattribs=attrs)


def _fix_diameter_second_arrow(
    dimension: _DxfEntity, center: Point2D, radius: float, location: Point2D, style: DimensionStyle
) -> None:
    """ezdxf's diameter renderer uses arrow 1 for both ends."""
    block = cast("_NativeDimension", dimension).get_geometry_block()
    native = cast("Dimension", dimension)
    document = native.doc
    length = math.dist(center, location)
    if block is None or document is None or length <= 1e-10:
        return
    opposite = (
        center[0] - radius * (location[0] - center[0]) / length,
        center[1] - radius * (location[1] - center[1]) / length,
    )
    arrow_name = {
        "open": "OPEN",
        "closed": "CLOSED",
        "filled": "",
        "tick": "OBLIQUE",
        "none": "NONE",
    }[style.arrow_second]
    for entity in tuple(block):
        if entity.dxftype() != "INSERT" or math.dist(tuple(entity.dxf.insert)[:2], opposite) > 1e-7:
            continue
        old_connection = _arrow_connection(
            entity.dxf.name, entity.dxf.insert, entity.dxf.xscale, entity.dxf.rotation
        )
        new_connection = _arrow_connection(
            arrow_name, entity.dxf.insert, entity.dxf.xscale, entity.dxf.rotation
        )
        entity.dxf.name = ARROWS.create_block(document.blocks, arrow_name)
        for stroke in block:
            if stroke.dxftype() != "LINE":
                continue
            for end in ("start", "end"):
                point = getattr(stroke.dxf, end)
                if math.dist(tuple(point)[:2], tuple(old_connection)) < 1e-7:
                    setattr(stroke.dxf, end, (new_connection[0], new_connection[1], 0.0))


def _dimension_native_snapshot(
    entity: _DxfEntity, *, include_style: bool = True, version: int = 7
) -> dict[str, object]:
    snapshot: dict[str, object] = {}
    for name in _DIMENSION_SNAPSHOT_FIELDS:
        try:
            value = entity.dxf.get(name)
        except DXFAttributeError:
            value = None
        if value is None or isinstance(value, str | int | float):
            snapshot[name] = value
        else:
            snapshot[name] = tuple(cast("Iterable[float]", value))
    if include_style:
        style = cast("_NativeDimension", entity).override()
        fields = (
            _DIMENSION_STYLE_V7_FIELDS
            if version >= 7
            else _DIMENSION_STYLE_V6_FIELDS
            if version >= 6
            else _DIMENSION_STYLE_V5_FIELDS
            if version >= 5
            else _DIMENSION_STYLE_V4_FIELDS
            if version >= 4
            else _DIMENSION_STYLE_V3_FIELDS
            if version >= 3
            else _DIMENSION_STYLE_FIELDS
        )
        for name in fields:
            snapshot[f"style:{name}"] = style.get(name, _DIMENSION_STYLE_DEFAULTS.get(name))
    return snapshot


def _dimension_snapshot_changes(entity: _DxfEntity) -> tuple[str, ...] | None:
    values = _xdata_values(entity, _DIMENSION_SNAPSHOT_APPID)
    if not values:
        return None
    if values[0] not in ("1", "2", "3", "4", "5", "6", "7"):
        raise ValueError("原生标注快照版本不受支持")
    raw_previous: object = json.loads("".join(values[1:]))
    if not isinstance(raw_previous, dict):
        raise ValueError("原生标注快照无效")
    previous = cast("dict[str, object]", raw_previous)
    expected_fields: set[str] = set(_DIMENSION_SNAPSHOT_FIELDS)
    if values[0] in ("2", "3", "4", "5", "6", "7"):
        fields = (
            _DIMENSION_STYLE_V7_FIELDS
            if values[0] == "7"
            else _DIMENSION_STYLE_V6_FIELDS
            if values[0] == "6"
            else _DIMENSION_STYLE_V5_FIELDS
            if values[0] == "5"
            else _DIMENSION_STYLE_V4_FIELDS
            if values[0] == "4"
            else _DIMENSION_STYLE_V3_FIELDS
            if values[0] == "3"
            else _DIMENSION_STYLE_FIELDS
        )
        expected_fields.update(f"style:{name}" for name in fields)
    if set(previous) != expected_fields:
        raise ValueError("原生标注快照无效")
    current = _dimension_native_snapshot(
        entity, include_style=values[0] != "1", version=int(values[0])
    )

    def same(left: object, right: object) -> bool:
        if isinstance(left, int | float) and isinstance(right, int | float):
            return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-9)
        if isinstance(left, list | tuple) and isinstance(right, list | tuple):
            left_items, right_items = (
                cast("Sequence[object]", left),
                cast("Sequence[object]", right),
            )
            return len(left_items) == len(right_items) and all(
                same(a, b) for a, b in zip(left_items, right_items, strict=True)
            )
        return left == right

    def normalized(name: str, value: object) -> object:
        if value is None and name.startswith("style:"):
            return _DIMENSION_STYLE_DEFAULTS.get(name.removeprefix("style:"))
        if value is None and name in ("horizontal_direction", "text_rotation"):
            return 0.0
        if (
            name == "dimtype"
            and entity.dxftype() == "ARC_DIMENSION"
            and isinstance(value, int)
            and (value & 15) in (5, 8)
        ):
            return (value & ~15) | 5
        return value

    return tuple(
        name
        for name in sorted(expected_fields)
        if not same(normalized(name, previous[name]), normalized(name, current[name]))
    )


class _NamedTable(Protocol):
    def __contains__(self, name: object) -> bool: ...

    def new(self, name: str, *, dxfattribs: Mapping[str, object] | None = None) -> object: ...


class _LayerInfo(Protocol):
    dxf: _DxfLayerAttributes

    def is_off(self) -> bool: ...

    def is_locked(self) -> bool: ...

    def is_frozen(self) -> bool: ...

    def off(self) -> None: ...

    def lock(self) -> None: ...

    def freeze(self) -> None: ...


class _LayerTable(_NamedTable, Protocol):
    def __iter__(self) -> Iterator[_LayerInfo]: ...

    def get(self, name: str) -> _LayerInfo: ...


class _DxfLayerAttributes(Protocol):
    def get(self, name: str, default: object = None) -> object: ...

    def __setattr__(self, name: str, value: object) -> None: ...


class _LinetypeInfo(Protocol):
    def setup_pattern(self, pattern: Sequence[float], length: float = 0.0) -> None: ...


class _LinetypeTable(_NamedTable, Protocol):
    def get(self, name: str) -> _LinetypeInfo: ...


class _Layout(Protocol):
    def __len__(self) -> int: ...


class _LayoutTable(Protocol):
    def get(self, name: str) -> _Layout: ...


class _Drawing(Protocol):
    header: MutableMapping[str, object]
    appids: _NamedTable
    layers: _LayerTable
    linetypes: _LinetypeTable
    layouts: _LayoutTable
    dxfversion: str

    def modelspace(self) -> _Modelspace: ...

    def saveas(self, path: Path) -> None: ...

    def layout_names(self) -> Sequence[str]: ...


class _NewDxf(Protocol):
    def __call__(self, dxfversion: str, *, units: int) -> _Drawing: ...


class _ReadDxf(Protocol):
    def __call__(self, path: Path) -> _Drawing: ...


_new_r2010 = cast("_NewDxf", _new_dxf)
_read_dxf_file = cast("_ReadDxf", vars(_filemanagement)["readfile"])


def _write_layers(document: _Drawing, layers: SketchLayerTable) -> None:
    for linetype, name in _DXF_LINETYPE_NAMES.items():
        if name not in document.linetypes:
            definition = cast(
                "_LinetypeInfo",
                document.linetypes.new(name, dxfattribs={"description": name}),
            )
            definition.setup_pattern(_DXF_LINETYPE_PATTERNS[linetype])
    for layer in layers.layers:
        color = (layer.color_rgb[0] << 16) | (layer.color_rgb[1] << 8) | layer.color_rgb[2]
        attributes = {
            "color": 7,
            "true_color": color,
            "linetype": _DXF_LINETYPE_NAMES[layer.linetype],
            "lineweight": round(layer.lineweight_mm * 100.0),
        }
        if layer.name.casefold() == "0":
            info = document.layers.get("0")
            for name, value in attributes.items():
                setattr(info.dxf, name, value)
        else:
            info = cast("_LayerInfo", document.layers.new(layer.name, dxfattribs=attributes))
        if not layer.visible:
            info.off()
        if layer.locked:
            info.lock()
        if layer.frozen:
            info.freeze()


def _sketch_entity(sketch: Sketch, reference: SketchGeometryReference) -> SketchEntity:
    try:
        return next(entity for entity in sketch.entities if entity.entity_id == reference.entity_id)
    except StopIteration as exc:
        raise ValueError(f"标注引用了不存在的图元 {reference.entity_id[:8]}") from exc


def _dimension_point(sketch: Sketch, reference: SketchGeometryReference) -> tuple[float, float]:
    entity = _sketch_entity(sketch, reference)
    if isinstance(entity, SplineEntity):
        if reference.kind == "start":
            return entity.control_points_mm[0]
        if reference.kind == "end":
            return entity.control_points_mm[-1]
        if reference.kind == "vertex" and reference.index is not None:
            return _indexed_point(entity.control_points_mm, reference.index)
    if isinstance(entity, LineEntity):
        if reference.kind == "start":
            return entity.start_mm
        if reference.kind == "end":
            return entity.end_mm
    elif isinstance(entity, PolylineEntity):
        if reference.kind == "start":
            return entity.points_mm[0]
        if reference.kind == "end":
            return entity.points_mm[-1]
        if reference.kind == "vertex" and reference.index is not None:
            return _indexed_point(entity.points_mm, reference.index)
    elif isinstance(entity, RectangleEntity):
        x1, y1 = entity.first_corner_mm
        x2, y2 = entity.opposite_corner_mm
        corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        if reference.kind == "start":
            return corners[0]
        if reference.kind == "end":
            return corners[2]
        if reference.kind == "vertex" and reference.index is not None:
            return _indexed_point(corners, reference.index)
    elif isinstance(entity, CircleEntity) and reference.kind in ("center", "geometry"):
        return entity.center_mm
    elif isinstance(entity, ArcEntity):
        if reference.kind in ("center", "geometry"):
            return entity.center_mm
        if reference.kind in ("start", "end"):
            angle = entity.start_angle_deg
            if reference.kind == "end":
                angle += entity.sweep_angle_deg
            radians = math.radians(angle)
            return (
                entity.center_mm[0] + entity.radius_mm * math.cos(radians),
                entity.center_mm[1] + entity.radius_mm * math.sin(radians),
            )
    raise ValueError(f"{reference.kind} 不是此尺寸支持的点引用")


def _indexed_point(points: tuple[tuple[float, float], ...], index: int) -> tuple[float, float]:
    if index >= len(points):
        raise ValueError(f"标注点索引 {index} 超出图元范围")
    return points[index]


def _dimension_line(
    sketch: Sketch, reference: SketchGeometryReference
) -> tuple[tuple[float, float], tuple[float, float]]:
    entity = _sketch_entity(sketch, reference)
    if isinstance(entity, LineEntity) and reference.kind == "geometry":
        return entity.start_mm, entity.end_mm
    if isinstance(entity, PolylineEntity) and reference.kind == "segment":
        if reference.index is None:
            raise ValueError("折线标注线段需要索引")
        if entity.bulges and entity.bulges[reference.index] != 0:
            raise ValueError("圆弧段不能作为直线标注")
        next_index = reference.index + 1
        if entity.closed:
            next_index %= len(entity.points_mm)
        return (
            _indexed_point(entity.points_mm, reference.index),
            _indexed_point(entity.points_mm, next_index),
        )
    if isinstance(entity, RectangleEntity) and reference.kind == "segment":
        if reference.index is None or reference.index >= 4:
            raise ValueError("矩形标注线段索引必须在 0 到 3 之间")
        x1, y1 = entity.first_corner_mm
        x2, y2 = entity.opposite_corner_mm
        corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        return corners[reference.index], corners[(reference.index + 1) % 4]
    raise ValueError("线性或角度标注需要直线或多段线线段引用")


def _line_intersection(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    p, p_end = first
    q, q_end = second
    r = (p_end[0] - p[0], p_end[1] - p[1])
    s = (q_end[0] - q[0], q_end[1] - q[1])
    denominator = r[0] * s[1] - r[1] * s[0]
    if abs(denominator) <= 1e-12:
        raise ValueError("平行线或重合线没有唯一角度标注顶点")
    difference = (q[0] - p[0], q[1] - p[1])
    parameter = (difference[0] * s[1] - difference[1] * s[0]) / denominator
    return (p[0] + parameter * r[0], p[1] + parameter * r[1])


def _dimension_style(constraint: SketchConstraint) -> dict[str, object]:
    text_size = 2.5 * constraint.scale
    return {
        "dimdec": constraint.precision,
        "dimadec": constraint.precision,
        "dimazin": 0,
        "dimaunit": 0,
        "dimdsep": ord("."),
        "dimtxt": text_size,
        "dimasz": text_size,
        "dimtad": 1,
        "dimzin": 0,
        "dimlfac": 1.0,
    }


def _measure_imported_dimension(sketch: Sketch, constraint: SketchConstraint) -> float:
    first_ref = constraint.references[0]
    if constraint.kind in ("length", "distance"):
        if constraint.kind == "length":
            first, second = _dimension_line(sketch, first_ref)
        else:
            first = _dimension_point(sketch, first_ref)
            second = _dimension_point(sketch, constraint.references[1])
        dx, dy = second[0] - first[0], second[1] - first[1]
        if constraint.axis == "aligned":
            return math.hypot(dx, dy)
        if constraint.projection_axis is not None:
            direction = constraint.projection_axis
            projection = dx * direction[0] + dy * direction[1]
        else:
            projection = dx if constraint.axis in ("horizontal", "ordinate_x") else dy
        return projection if constraint.axis.startswith("ordinate_") else abs(projection)
    if constraint.kind == "angle":
        first_start, first_end = _dimension_line(sketch, first_ref)
        second_start, second_end = _dimension_line(sketch, constraint.references[1])
        ax, ay = first_end[0] - first_start[0], first_end[1] - first_start[1]
        bx, by = second_end[0] - second_start[0], second_end[1] - second_start[1]
        return math.degrees(math.atan2(ax * by - ay * bx, ax * bx + ay * by))
    entity = _sketch_entity(sketch, first_ref)
    if constraint.kind == "arc_length" and isinstance(entity, ArcEntity):
        return entity.radius_mm * abs(math.radians(entity.sweep_angle_deg))
    if constraint.kind in ("radius", "diameter") and isinstance(entity, CircleEntity | ArcEntity):
        return entity.radius_mm * (2 if constraint.kind == "diameter" else 1)
    raise ValueError("导入的图元不支持该尺寸")


def _write_dimension(
    modelspace: _Modelspace,
    sketch: Sketch,
    constraint: SketchConstraint,
    *,
    measurement_angle: float | None = None,
    reflect_angle: bool = False,
    write_metadata: bool = True,
    drawing_style: DimensionStyle | None = None,
) -> None:
    if constraint.kind not in ("length", "distance", "angle", "radius", "diameter", "arc_length"):
        raise ValueError("只支持长度、距离、角度、半径和直径标注")
    if constraint.value is None:
        raise ValueError("尺寸没有可显示的数值")
    first_reference = constraint.references[0]
    first_entity = _sketch_entity(sketch, first_reference)
    attributes: Mapping[str, object] = {"layer": constraint.layer_name or first_entity.layer_name}
    if constraint.text_override is None:
        text = "<>" if constraint.kind == "angle" else "<> mm"
    else:
        text = (
            constraint.text_override.replace("\\", "\\\\").replace("{", r"\{").replace("}", r"\}")
        )
        # Empty MTEXT groups keep adjacent literal '%' characters from forming %% codes.
        text = re.sub(r"%(?=%)", "%{}", text)
        if text.count("<>") > 1:
            first, rest = text.split("<>", 1)
            display_value = constraint.value
            if constraint.kind == "angle" and constraint.position_mm is not None:
                first_line = _dimension_line(sketch, constraint.references[0])
                second_line = _dimension_line(sketch, constraint.references[1])
                display_value = math.degrees(
                    angular_sector(first_line, second_line, constraint.position_mm).sweep
                )
            number = f"{display_value:.{constraint.precision}f}"
            text = first + "<>" + rest.replace("<>", number)
    override = _dimension_style(constraint)
    if drawing_style is not None:
        arrows = {
            "open": "OPEN",
            "closed": "CLOSED",
            "filled": "",
            "tick": "OBLIQUE",
            "none": "NONE",
        }
        override.update(
            {
                "dimsah": 1,
                "dimclrd": drawing_style.dimension_color,
                "dimclre": drawing_style.extension_color,
                "dimclrt": drawing_style.text_color,
                "dimlwd": drawing_style.dimension_lineweight,
                "dimlwe": drawing_style.extension_lineweight,
                "dimse1": int(drawing_style.suppress_extension_first),
                "dimse2": int(drawing_style.suppress_extension_second),
                "dimsd1": int(drawing_style.suppress_dimension_first),
                "dimsd2": int(drawing_style.suppress_dimension_second),
                "dimltype": "BYLAYER"
                if drawing_style.dimension_linetype == "BYLAYER"
                else _DXF_LINETYPE_NAMES[cast("SketchLinetype", drawing_style.dimension_linetype)],
                "dimltex1": "BYLAYER"
                if drawing_style.extension_linetype_first == "BYLAYER"
                else _DXF_LINETYPE_NAMES[
                    cast("SketchLinetype", drawing_style.extension_linetype_first)
                ],
                "dimltex2": "BYLAYER"
                if drawing_style.extension_linetype_second == "BYLAYER"
                else _DXF_LINETYPE_NAMES[
                    cast("SketchLinetype", drawing_style.extension_linetype_second)
                ],
                "dimblk1": arrows[drawing_style.arrow_first],
                "dimblk2": arrows[drawing_style.arrow_second],
                "dimasz": drawing_style.arrow_size * constraint.scale,
                "dimdle": drawing_style.dimline_extension * constraint.scale,
                "dimexe": drawing_style.extline_extension * constraint.scale,
                "dimexo": drawing_style.extline_offset * constraint.scale,
                "dimtxt": drawing_style.text_height * constraint.scale,
                "dimcen": drawing_style.center_size
                * constraint.scale
                * {"none": 0, "mark": 1, "line": -1}[drawing_style.center_mark],
            }
        )
        if drawing_style.suppress_dimension_first:
            override["suppress_arrow1"] = True
        if drawing_style.suppress_dimension_second:
            override["suppress_arrow2"] = True
    offset = max(5.0 * constraint.scale, 2.5 * constraint.scale)
    angular_clip: tuple[Point2D, float, float, float, Point2D] | None = None
    radial_clip: tuple[Point2D, float, Point2D] | None = None

    if constraint.kind in ("length", "distance"):
        if constraint.kind == "length":
            first, second = _dimension_line(sketch, first_reference)
        else:
            first = _dimension_point(sketch, first_reference)
            second = _dimension_point(sketch, constraint.references[1])
        if constraint.axis.startswith("ordinate_"):
            location = constraint.position_mm or (second[0] + offset, second[1] + offset)
            # DXF uses DIMRND=0 for no extra rounding, but ezdxf's renderer
            # rounds that value to an integer after a saved file is reopened.
            # Match the visible precision when the native dimension is rerendered.
            override["dimrnd"] = 10.0**-constraint.precision
            if constraint.value < 0:
                text = text.replace("<>", "-<>")
            result = modelspace.add_ordinate_dim(
                feature_location=second,
                offset=(location[0] - second[0], location[1] - second[1]),
                dtype=1 if constraint.axis == "ordinate_x" else 0,
                origin=first,
                text=text,
                override=override,
                dxfattribs=attributes,
            )
            if measurement_angle is not None:
                result.dimension.dxf.horizontal_direction = -measurement_angle
        elif constraint.axis in ("horizontal", "vertical"):
            result = modelspace.add_linear_dim(
                base=constraint.position_mm or (first[0] + offset, first[1] + offset),
                p1=first,
                p2=second,
                angle=measurement_angle
                if measurement_angle is not None
                else 0.0
                if constraint.axis == "horizontal"
                else 90.0,
                text=text,
                override=override,
                dxfattribs=attributes,
            )
        else:
            distance = offset
            if constraint.position_mm is not None:
                dx, dy = second[0] - first[0], second[1] - first[1]
                length = math.hypot(dx, dy)
                if length > 1e-12:
                    distance = (
                        -(constraint.position_mm[0] - first[0]) * dy
                        + (constraint.position_mm[1] - first[1]) * dx
                    ) / length
            result = modelspace.add_aligned_dim(
                p1=first,
                p2=second,
                distance=distance,
                text=text,
                override=override,
                dxfattribs=attributes,
            )
    elif constraint.kind == "arc_length":
        if not isinstance(first_entity, ArcEntity):
            raise ValueError("弧长标注需要圆弧")
        start, end = _dxf_arc_angles(first_entity)
        center = first_entity.center_mm
        radius = first_entity.radius_mm

        def arc_point(degrees: float) -> tuple[float, float]:
            return (
                center[0] + radius * math.cos(math.radians(degrees)),
                center[1] + radius * math.sin(math.radians(degrees)),
            )

        location = constraint.position_mm or (
            center[0] + radius + offset,
            center[1] + radius + offset,
        )
        if first_entity.sweep_angle_deg < 0 and drawing_style is not None:
            _swap_dimension_end_styles(override)
        angular_clip = (
            center,
            math.hypot(location[0] - center[0], location[1] - center[1]),
            math.radians(start),
            math.radians((end - start) % 360.0),
            location,
        )
        result = modelspace.add_arc_dim_3p(
            base=location,
            center=center,
            p1=arc_point(start),
            p2=arc_point(end),
            location=location,
            text=text,
            override=override,
            dxfattribs=attributes,
        )
    elif constraint.kind == "angle":
        line1 = _dimension_line(sketch, first_reference)
        line2 = _dimension_line(sketch, constraint.references[1])
        vertex = _line_intersection(line1, line2)
        reverse_style = False
        first_vector = (line1[1][0] - line1[0][0], line1[1][1] - line1[0][1])
        second_vector = (line2[1][0] - line2[0][0], line2[1][1] - line2[0][1])
        # Native three-point dimensions keep measured and rendered rays in
        # the same order. Two-line dimensions can render the complementary
        # sector even when get_measurement() reports the intended angle.
        if constraint.position_mm is not None:
            sector = angular_sector(line1, line2, constraint.position_mm)
            reverse_style = not sector.starts_with_first
            first_vector = (math.cos(sector.start), math.sin(sector.start))
            end = sector.start + sector.sweep
            second_vector = (math.cos(end), math.sin(end))
        else:
            if constraint.value < 0:
                first_vector, second_vector = second_vector, first_vector
                reverse_style = not reverse_style
                text = text.replace("<>", "-<>")
            if reflect_angle:
                first_vector, second_vector = second_vector, first_vector
                reverse_style = not reverse_style
        if reverse_style and drawing_style is not None:
            # DXF three-point dimensions number styles by arc endpoint, while
            # MyCAD numbers them by the selected reference line.
            _swap_dimension_end_styles(override)
        start_angle = math.atan2(first_vector[1], first_vector[0])
        end_angle = math.atan2(second_vector[1], second_vector[0])
        sweep = (end_angle - start_angle) % math.tau
        middle_angle = start_angle + sweep / 2.0
        location = (
            vertex[0] + offset * math.cos(middle_angle),
            vertex[1] + offset * math.sin(middle_angle),
        )
        location = constraint.position_mm or location
        angular_clip = (
            vertex,
            math.hypot(location[0] - vertex[0], location[1] - vertex[1]),
            start_angle,
            sweep,
            location,
        )
        result = modelspace.add_angular_dim_3p(
            base=location,
            center=vertex,
            p1=(vertex[0] + first_vector[0], vertex[1] + first_vector[1]),
            p2=(vertex[0] + second_vector[0], vertex[1] + second_vector[1]),
            location=location,
            text=text,
            override=override,
            dxfattribs=attributes,
        )
    else:
        if not isinstance(first_entity, CircleEntity | ArcEntity):
            raise ValueError("半径和直径标注需要圆或圆弧引用")
        center = first_entity.center_mm
        radius = first_entity.radius_mm
        angle = 45.0
        radians = math.radians(angle)
        reach = radius + offset
        location = (center[0] + reach * math.cos(radians), center[1] + reach * math.sin(radians))
        location = constraint.position_mm or location
        radial_clip = (center, radius, location)
        angle = math.degrees(math.atan2(location[1] - center[1], location[0] - center[0]))
        factory = (
            modelspace.add_radius_dim
            if constraint.kind == "radius"
            else modelspace.add_diameter_dim
        )
        result = factory(
            center=center,
            radius=radius,
            angle=angle,
            location=location,
            text=text,
            override=override,
            dxfattribs=attributes,
        )

    try:
        if constraint.text_position_mm is not None:
            result.set_location(constraint.text_position_mm, leader=True)
        radial_first = (
            radial_clip is not None
            and drawing_style is not None
            and bool(override.get("dimsd1", 0))
        )
        if radial_first:
            # ezdxf otherwise skips the entire radius/diameter geometry block.
            result["dimsd1"] = 0
        result.render()
        if radial_first:
            result["dimsd1"] = 1
            result.commit()
        if radial_clip is not None and drawing_style is not None:
            radial_center, radial_radius, radial_location = radial_clip
            if constraint.kind == "diameter":
                _fix_diameter_second_arrow(result.dimension, *radial_clip, drawing_style)
            radial_second = constraint.kind == "diameter" and bool(override.get("dimsd2", 0))
            if radial_first or radial_second:
                _clip_radial_dimension_line(
                    result.dimension,
                    radial_center,
                    radial_location,
                    constraint.text_position_mm or radial_location,
                    radius_dimension=constraint.kind == "radius",
                    suppress_first=radial_first,
                    suppress_second=radial_second,
                )
            if math.dist(radial_center, radial_location) > radial_radius:
                _add_radial_center_mark(
                    result.dimension,
                    radial_center,
                    radial_radius,
                    drawing_style,
                    constraint.scale,
                )
        if angular_clip is not None and drawing_style is not None:
            suppress_start = bool(override.get("dimsd1", 0))
            suppress_end = bool(override.get("dimsd2", 0))
            if suppress_start or suppress_end:
                vertex, radius, start_angle, sweep, location = angular_clip
                label = constraint.text_position_mm or location
                label_angle = math.atan2(label[1] - vertex[1], label[0] - vertex[0])
                split = (label_angle - start_angle) % math.tau
                if split > sweep:
                    split = 0.0 if math.tau - split < split - sweep else sweep
                _clip_angular_dimension_line(
                    result.dimension,
                    vertex,
                    radius,
                    start_angle,
                    sweep,
                    split,
                    suppress_start,
                    suppress_end,
                )
        if not write_metadata:
            return
        metadata = constraint.to_mapping()
        metadata.pop("style_name", None)
        payload = json.dumps(
            metadata,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        result.dimension.set_xdata(
            _APPID,
            [(1000, sketch.sketch_id), (1000, "dimension")]
            + [(1000, payload[index : index + 240]) for index in range(0, len(payload), 240)],
        )
        snapshot = json.dumps(
            _dimension_native_snapshot(result.dimension),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        result.dimension.set_xdata(
            _DIMENSION_SNAPSHOT_APPID,
            [(1000, "7")]
            + [(1000, snapshot[index : index + 240]) for index in range(0, len(snapshot), 240)],
        )
        if drawing_style is not None:
            style_payload = json.dumps(
                drawing_style.to_mapping(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            digest = hashlib.sha256((snapshot + "\n" + style_payload).encode("utf-8")).hexdigest()
            result.dimension.set_xdata(
                _DIMENSION_STYLE_APPID,
                [(1000, "2"), (1000, digest)]
                + [
                    (1000, style_payload[index : index + 240])
                    for index in range(0, len(style_payload), 240)
                ],
            )
    except (TypeError, ValueError):
        modelspace.delete_entity(result.dimension)
        raise


def _read_layers(document: _Drawing, warnings: list[str]) -> SketchLayerTable:
    result = SketchLayerTable()
    known_names = {"0"}
    for info in document.layers:
        raw_name = info.dxf.get("name", "")
        if not isinstance(raw_name, str):
            warnings.append("DXF 含无效图层名称，已忽略该图层定义")
            continue
        if raw_name.casefold() in known_names:
            if raw_name.casefold() == "0":
                layer = _read_layer_info(info, warnings)
                result = result.replace(layer)
            continue
        if raw_name.casefold() == "defpoints":
            continue
        if raw_name.casefold() == _CONSTRUCTION_LAYER.casefold():
            # Historical MyCAD exports used this special layer to mark
            # construction geometry; its old entities import onto layer 0.
            continue
        try:
            layer = _read_layer_info(info, warnings)
            result = result.add(layer)
        except ValueError as exc:
            warnings.append(f"DXF 图层 {raw_name!r} 未能保留：{exc}")
            continue
        known_names.add(raw_name.casefold())
    return result


def _read_layer_info(info: _LayerInfo, warnings: list[str]) -> SketchLayer:
    raw_name = info.dxf.get("name", "")
    name = raw_name if isinstance(raw_name, str) else ""
    true_color = info.dxf.get("true_color")
    if (
        isinstance(true_color, int)
        and not isinstance(true_color, bool)
        and 0 <= true_color <= 0xFFFFFF
    ):
        rgb = int2rgb(true_color)
    else:
        aci = info.dxf.get("color", 7)
        color_index = abs(aci) if isinstance(aci, int) and not isinstance(aci, bool) else 7
        if color_index < 1 or color_index > 255:
            color_index = 7
        rgb = aci2rgb(color_index)

    raw_linetype = info.dxf.get("linetype", "CONTINUOUS")
    dxf_linetype = raw_linetype.upper() if isinstance(raw_linetype, str) else ""
    linetype = _DXF_LINETYPE_VALUES.get(dxf_linetype)
    if linetype is None:
        warnings.append(f"DXF 图层 {name} 的线型 {raw_linetype!r} 不在交换子集中，按连续线导入")
        linetype = "CONTINUOUS"

    raw_lineweight = info.dxf.get("lineweight", 25)
    if (
        isinstance(raw_lineweight, int)
        and not isinstance(raw_lineweight, bool)
        and raw_lineweight >= 0
    ):
        weight = raw_lineweight / 100.0
        lineweight = min(STANDARD_LINEWEIGHTS_MM, key=lambda value: abs(value - weight))
        if not math.isclose(weight, lineweight, abs_tol=1e-9):
            warnings.append(
                f"DXF 图层 {name} 的线宽 {weight:g} mm 不受支持，按 {lineweight:g} mm 导入"
            )
    else:
        lineweight = DEFAULT_SKETCH_LAYER.lineweight_mm

    return SketchLayer(
        name=name,
        color_rgb=(rgb.r, rgb.g, rgb.b),
        linetype=linetype,
        lineweight_mm=lineweight,
        visible=not info.is_off(),
        locked=info.is_locked(),
        frozen=info.is_frozen(),
    )


def _write_dxf(geometry: ExportableKernel, path: Path) -> DxfExchangeReport:
    if not isinstance(geometry, _SketchSource):
        raise ValidationError("DXF 导出需要提供草图数据的几何内核。")
    styles = (
        geometry.drawing_dimension_styles if isinstance(geometry, _DimensionStyleSource) else None
    )
    report = write_sketches_dxf(geometry.sketches, path, dimension_styles=styles)
    if isinstance(geometry, _CrossTangencySource) and geometry.cross_sketch_tangencies:
        report = DxfExchangeReport(
            report.action,
            report.dxf_version,
            report.unit,
            report.entity_count,
            (*report.warnings, f"{len(geometry.cross_sketch_tangencies)} 个对象相切关系未导出"),
        )
    if isinstance(geometry, _ArraySource) and geometry.associative_arrays:
        report = DxfExchangeReport(
            report.action,
            report.dxf_version,
            report.unit,
            report.entity_count,
            (
                *report.warnings,
                f"{len(geometry.associative_arrays)} 个关联阵列已导出为独立图元，关联关系未导出",
            ),
        )
    if isinstance(geometry, _RasterSource) and geometry.drawing_rasters:
        report = DxfExchangeReport(
            report.action,
            report.dxf_version,
            report.unit,
            report.entity_count,
            (*report.warnings, f"{len(geometry.drawing_rasters)} 张嵌入图片未导出"),
        )
    if geometry.mass_properties().solid_count:
        report = DxfExchangeReport(
            report.action,
            report.dxf_version,
            report.unit,
            report.entity_count,
            (*report.warnings, "文件仅包含二维草图，当前三维实体未导出"),
        )
    return report


class DxfSketchProvider(FormatProvider):
    """Registered DXF provider with a sketch-specific read entry point."""

    def read_sketch(self, path: Path, *, unit_override: str | None = None) -> DxfSketchImport:
        """Read one supported 2D sketch; callers must present its report."""
        return read_sketch_dxf(path, unit_override=unit_override)


def write_sketch_dxf(sketch: Sketch, path: Path) -> DxfExchangeReport:
    """Write supported entities to DXF R2010 and report non-DXF semantics."""
    return write_sketches_dxf((sketch,), path)


def _project_export_sketch(
    sketch: Sketch, frame: WorkPlaneFrame
) -> tuple[Sketch, tuple[str, ...], dict[str, tuple[float | None, bool]]]:
    """Re-express one coplanar sketch in the export frame without flattening geometry."""

    def explicit_angle(constraint: SketchConstraint) -> float:
        if constraint.projection_axis is None:
            raise ValueError("尺寸没有显式投影轴")
        local_u, local_v = constraint.projection_axis
        direction = tuple(
            local_u * sketch.frame.u_axis[index] + local_v * sketch.frame.v_axis[index]
            for index in range(3)
        )
        x = sum(a * b for a, b in zip(direction, frame.u_axis, strict=True))
        y = sum(a * b for a, b in zip(direction, frame.v_axis, strict=True))
        angle = math.degrees(math.atan2(y, x))
        return angle - 90.0 if constraint.axis == "ordinate_y" else angle

    if sketch.frame == frame:
        return (
            sketch,
            (),
            {
                constraint.constraint_id: (explicit_angle(constraint), False)
                for constraint in sketch.constraints
                if constraint.projection_axis is not None
            },
        )
    same_axes = sketch.frame.u_axis == frame.u_axis and sketch.frame.v_axis == frame.v_axis
    normal_dot = sum(a * b for a, b in zip(sketch.frame.normal, frame.normal, strict=True))

    def project(point: Point2D) -> Point2D:
        return frame.world_to_local(sketch.frame.local_to_world(point))

    entities: list[SketchEntity] = []
    warnings: list[str] = []
    for entity in sketch.entities:
        if isinstance(entity, LineEntity | CircleEntity | ArcEntity):
            entities.append(project_tangent_entity(entity, sketch.frame, frame))
        elif isinstance(entity, PolylineEntity):
            entities.append(project_polyline_entity(entity, sketch.frame, frame))
        elif isinstance(entity, PointEntity):
            entities.append(replace(entity, position_mm=project(entity.position_mm)))
        elif isinstance(entity, SplineEntity):
            entities.append(
                replace(
                    entity,
                    control_points_mm=tuple(project(point) for point in entity.control_points_mm),
                )
            )
        elif same_axes:
            entities.append(
                replace(
                    entity,
                    first_corner_mm=project(entity.first_corner_mm),
                    opposite_corner_mm=project(entity.opposite_corner_mm),
                )
            )
        else:
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            points = tuple(project(point) for point in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)))
            entities.append(
                PolylineEntity(
                    entity.entity_id, points, True, entity.construction, entity.layer_name
                )
            )
            warnings.append(f"旋转草图中的矩形 {entity.entity_id[:8]} 已导出为闭合多段线")
    constraints: list[SketchConstraint] = []
    measurement_angles: dict[str, tuple[float | None, bool]] = {}
    converted_rectangles = {
        entity.entity_id
        for entity in sketch.entities
        if isinstance(entity, RectangleEntity) and not same_axes
    }
    for constraint in sketch.constraints:
        if constraint.projection_axis is not None:
            measurement_angles[constraint.constraint_id] = (explicit_angle(constraint), False)
        elif not same_axes and constraint.axis in (
            "horizontal",
            "vertical",
            "ordinate_x",
            "ordinate_y",
        ):
            axis = sketch.frame.v_axis if constraint.axis == "vertical" else sketch.frame.u_axis
            x = sum(a * b for a, b in zip(axis, frame.u_axis, strict=True))
            y = sum(a * b for a, b in zip(axis, frame.v_axis, strict=True))
            angle = math.degrees(math.atan2(y, x))
            if normal_dot < 0 and constraint.axis == "ordinate_y":
                angle += 180.0
            measurement_angles[constraint.constraint_id] = (angle, False)
        elif normal_dot < 0 and constraint.kind == "angle":
            measurement_angles[constraint.constraint_id] = (None, True)
        constraints.append(
            replace(
                constraint,
                references=tuple(
                    replace(ref, kind="vertex", index=0 if ref.kind == "start" else 2)
                    if ref.entity_id in converted_rectangles and ref.kind in ("start", "end")
                    else ref
                    for ref in constraint.references
                ),
                position_mm=None
                if constraint.position_mm is None
                else project(constraint.position_mm),
                text_position_mm=None
                if constraint.text_position_mm is None
                else project(constraint.text_position_mm),
                projection_axis=None
                if constraint.projection_axis is None
                else project_coplanar_vector(constraint.projection_axis, sketch.frame, frame),
            )
        )
    return (
        replace(
            sketch,
            frame=frame,
            entities=tuple(entities),
            constraints=tuple(constraints),
            support_face=None,
        ),
        tuple(warnings),
        measurement_angles,
    )


def _max_plane_distance(sketch: Sketch, reference: WorkPlaneFrame) -> float:
    """Bound the physical offset of all exported geometry from the reference plane."""
    normal = reference.normal
    origin = sum(
        (a - b) * n
        for a, b, n in zip(sketch.frame.origin_mm, reference.origin_mm, normal, strict=True)
    )
    u = sum(a * b for a, b in zip(sketch.frame.u_axis, normal, strict=True))
    v = sum(a * b for a, b in zip(sketch.frame.v_axis, normal, strict=True))
    maximum = abs(origin)
    if u == 0.0 and v == 0.0:
        return maximum

    def distance(point: Point2D) -> float:
        return abs(origin + u * point[0] + v * point[1])

    def arc_distance(arc: ArcEntity) -> float:
        extrema = [arc.start_angle_deg, arc.start_angle_deg + arc.sweep_angle_deg]
        peak = math.degrees(math.atan2(v, u))
        for angle in (peak, peak + 180.0):
            relative = (
                (angle - arc.start_angle_deg) % 360
                if arc.sweep_angle_deg > 0
                else (arc.start_angle_deg - angle) % 360
            )
            if relative <= abs(arc.sweep_angle_deg) + 1e-10:
                extrema.append(angle)
        return max(
            distance(
                (
                    arc.center_mm[0] + arc.radius_mm * math.cos(math.radians(angle)),
                    arc.center_mm[1] + arc.radius_mm * math.sin(math.radians(angle)),
                )
            )
            for angle in extrema
        )

    def spline_distance(spline: SplineEntity) -> float:
        # Each knot span is cubic. Its signed distance has extrema only at
        # endpoints or roots of its quadratic derivative.
        spans = len(spline.control_points_mm) - 3
        result = 0.0
        for index in range(spans):
            start = index / spans
            width = 1.0 / spans
            values = [
                u * point[0] + v * point[1]
                for point in (spline.point_at(min(1.0, start + width * j / 3)) for j in range(4))
            ]
            p0, f1, f2, p3 = values
            s1 = 27 * f1 - 8 * p0 - p3
            s2 = 27 * f2 - p0 - 8 * p3
            p1, p2 = (2 * s1 - s2) / 18, (2 * s2 - s1) / 18
            a = 3 * (-p0 + 3 * p1 - 3 * p2 + p3)
            b = 6 * (p0 - 2 * p1 + p2)
            c = 3 * (p1 - p0)
            scale = max(abs(a), abs(b), abs(c))
            candidates = [0.0, 1.0]
            if not math.isfinite(scale):
                return max(distance(point) for point in spline.control_points_mm)
            if scale:
                a, b, c = a / scale, b / scale, c / scale
                if a == 0:
                    if b:
                        candidates.append(-c / b)
                else:
                    discriminant = b * b - 4 * a * c
                    if discriminant >= 0:
                        root = math.sqrt(discriminant)
                        q = -0.5 * (b + math.copysign(root, b))
                        if q:
                            candidates.extend((q / a, c / q))
                        else:
                            candidates.append(-b / (2 * a))
            result = max(
                result,
                *(
                    distance(spline.point_at(min(1.0, start + width * t)))
                    for t in candidates
                    if 0 <= t <= 1
                ),
            )
        return result

    for entity in sketch.entities:
        if isinstance(entity, PointEntity):
            points = (entity.position_mm,)
        elif isinstance(entity, LineEntity):
            points = (entity.start_mm, entity.end_mm)
        elif isinstance(entity, PolylineEntity):
            points = entity.points_mm
            if entity.bulges:
                # Arc bulges can extend beyond their chord endpoints.
                for segment in polyline_curve_segments(
                    entity.points_mm, entity.bulges, entity.closed, entity.entity_id
                ):
                    if isinstance(segment, ArcEntity):
                        maximum = max(maximum, arc_distance(segment))
        elif isinstance(entity, SplineEntity):
            maximum = max(maximum, spline_distance(entity))
            continue
        elif isinstance(entity, RectangleEntity):
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            points = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        elif isinstance(entity, ArcEntity):
            maximum = max(maximum, arc_distance(entity))
            continue
        else:
            maximum = max(maximum, distance(entity.center_mm) + entity.radius_mm * math.hypot(u, v))
            continue
        maximum = max(maximum, *(distance(point) for point in points))
    return maximum


def write_sketches_dxf(
    sketches: tuple[Sketch, ...], path: Path, *, dimension_styles: DimensionStyleTable | None = None
) -> DxfExchangeReport:
    """Write coplanar sketch geometry without merging source identities."""
    if not sketches:
        raise ValidationError("DXF 导出至少需要一张草图。")
    if len({sketch.sketch_id for sketch in sketches}) != len(sketches):
        raise ValidationError("DXF 导出的草图身份不能重复。")
    reference = sketches[0].frame
    for sketch in sketches[1:]:
        source_normal = sketch.frame.normal
        target_normal = reference.normal
        cross_normal = (
            source_normal[1] * target_normal[2] - source_normal[2] * target_normal[1],
            source_normal[2] * target_normal[0] - source_normal[0] * target_normal[2],
            source_normal[0] * target_normal[1] - source_normal[1] * target_normal[0],
        )
        if math.hypot(*cross_normal) > 1e-9 or _max_plane_distance(sketch, reference) > 1e-7:
            raise ValidationError("DXF 多草图输出要求工作平面共面。")
    projected: list[tuple[Sketch, dict[str, tuple[float | None, bool]]]] = []
    warnings: list[str] = []
    for sketch in sketches:
        transformed, notices, measurement_angles = _project_export_sketch(sketch, reference)
        projected.append((transformed, measurement_angles))
        warnings.extend(notices)
    layers: dict[str, SketchLayer] = {}
    for sketch in sketches:
        for layer in sketch.layers.layers:
            key = layer.name.casefold()
            existing = layers.get(key)
            if existing is not None:
                if existing != replace(layer, name=existing.name):
                    raise ValidationError(f"DXF 图层 {layer.name} 在草图之间存在冲突。")
                if existing.name != layer.name:
                    notice = f"图层 {layer.name} 与 {existing.name} 仅大小写不同，DXF 合并为 {existing.name}"
                    if notice not in warnings:
                        warnings.append(notice)
            else:
                layers[key] = layer
    document = _new_r2010("R2010", units=4)
    document.header["$INSUNITS"] = 4
    document.header["$MEASUREMENT"] = 1
    document.appids.new(_APPID, dxfattribs=None)
    document.appids.new(_DIMENSION_SNAPSHOT_APPID, dxfattribs=None)
    document.appids.new(_DIMENSION_STYLE_APPID, dxfattribs=None)
    _write_layers(document, SketchLayerTable(tuple(layers.values())))
    modelspace = document.modelspace()
    exported_dimensions = 0
    for sketch, measurement_angles in projected:
        _write_sketch_entities(modelspace, sketch)
        for constraint in sketch.constraints:
            try:
                projection = measurement_angles.get(constraint.constraint_id)
                write_metadata = projection is None or constraint.projection_axis is not None
                _write_dimension(
                    modelspace,
                    sketch,
                    constraint,
                    measurement_angle=None if projection is None else projection[0],
                    reflect_angle=False if projection is None else projection[1],
                    write_metadata=write_metadata,
                    drawing_style=dimension_styles.get(constraint.style_name)
                    if dimension_styles is not None and constraint.style_name is not None
                    else None,
                )
            except (TypeError, ValueError) as exc:
                warnings.append(
                    f"尺寸/约束 {constraint.constraint_id[:8]} 未导出为 DXF 标注：{exc}"
                )
            else:
                exported_dimensions += 1
                if constraint.text_override and constraint.text_override.count("<>") > 1:
                    warnings.append(
                        f"尺寸 {constraint.constraint_id[:8]} 含多个数值占位符；"
                        "DXF 仅首个随测量更新，其余按导出时数值显示"
                    )
                if constraint.style_name is not None:
                    warnings.append(
                        f"尺寸 {constraint.constraint_id[:8]} 的 DXF 原生样式关联未导出；"
                        + (
                            "外观设置已导出，MyCAD 扩展数据可恢复图纸样式，其他软件可能不保留"
                            if dimension_styles is not None and write_metadata
                            else "DXF 保留当前尺寸外观设置"
                            if dimension_styles is not None
                            else "DXF 保留当前精度和比例"
                        )
                    )
                if projection is not None:
                    orientation = "原方向" if projection[1] else "原坐标轴"
                    dimension_notices: list[str] = []
                    if not write_metadata:
                        dimension_notices.append("导入 MyCAD 时不恢复关联")
                    if dimension_notices:
                        warnings.append(
                            f"尺寸 {constraint.constraint_id[:8]} 已按{orientation}导出，"
                            + "；".join(dimension_notices)
                        )
                if constraint.axis.startswith("ordinate_"):
                    warnings.append(
                        f"坐标尺寸 {constraint.constraint_id[:8]} 符号按导出时固定；"
                        "跨原点修改后需检查符号"
                    )
    document.saveas(path)
    if not any(sketch.entities for sketch in sketches):
        warnings.append("草图中没有可导出的二维图元")
    if reference != WorkPlaneFrame.xy():
        warnings.append("工作平面位姿未写入 DXF，图元按草图局部坐标投影到 XY")
    if len(sketches) > 1:
        warnings.append("多个草图导入 MyCAD 时将合并为单张草图，原草图分组不保留")
    return DxfExchangeReport(
        "导出",
        document.dxfversion,
        "mm",
        sum(len(sketch.entities) for sketch in sketches) + exported_dimensions,
        tuple(warnings),
    )


def _write_sketch_entities(modelspace: _Modelspace, sketch: Sketch) -> None:
    for entity in sketch.entities:
        is_rectangle = isinstance(entity, RectangleEntity)
        attributes = {"layer": entity.layer_name}
        if isinstance(entity, PointEntity):
            dxf_entity = modelspace.add_point(entity.position_mm, dxfattribs=attributes)
        elif isinstance(entity, SplineEntity):
            dxf_entity = modelspace.add_open_spline(
                ((u, v, 0.0) for u, v in entity.control_points_mm),
                degree=3,
                knots=entity.knots,
                dxfattribs=attributes,
            )
        elif isinstance(entity, LineEntity):
            dxf_entity = modelspace.add_line(entity.start_mm, entity.end_mm, dxfattribs=attributes)
        elif isinstance(entity, PolylineEntity):
            if entity.bulges:
                bulges = (*entity.bulges, 0.0) if not entity.closed else entity.bulges
                points = tuple(
                    (point[0], point[1], 0.0, 0.0, bulge)
                    for point, bulge in zip(entity.points_mm, bulges, strict=True)
                )
            else:
                points = entity.points_mm
            dxf_entity = modelspace.add_lwpolyline(
                points, close=entity.closed, dxfattribs=attributes
            )
        elif isinstance(entity, CircleEntity):
            dxf_entity = modelspace.add_circle(
                entity.center_mm, entity.radius_mm, dxfattribs=attributes
            )
        elif isinstance(entity, ArcEntity):
            start, end = _dxf_arc_angles(entity)
            dxf_entity = modelspace.add_arc(
                entity.center_mm,
                entity.radius_mm,
                start,
                end,
                dxfattribs=attributes,
            )
        else:
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            dxf_entity = modelspace.add_lwpolyline(
                ((x1, y1), (x2, y1), (x2, y2), (x1, y2)),
                close=True,
                dxfattribs=attributes,
            )
        sweep_sign = "cw" if isinstance(entity, ArcEntity) and entity.sweep_angle_deg < 0 else "ccw"
        dxf_entity.set_xdata(
            _APPID,
            [
                (1000, sketch.sketch_id),
                (1000, entity.entity_id),
                (1000, "rectangle" if is_rectangle else ""),
                (1000, sweep_sign),
                (1000, "1" if entity.construction else "0"),
            ],
        )


def read_sketch_dxf(path: Path, *, unit_override: str | None = None) -> DxfSketchImport:
    """Read 2D linework into one XY sketch; unsupported entities are reported."""
    document = _read_dxf_file(path)
    scale, unit_name = _unit_scale(document.header.get("$INSUNITS", 0), unit_override)
    warnings: list[str] = []
    layers = _read_layers(document, warnings)
    entities: list[SketchEntity] = []
    dimension_mappings: list[tuple[str, object, _DxfEntity]] = []
    known_sketch_ids: set[str] = set()
    used_entity_ids: set[str] = set()
    entity_id_map: dict[tuple[str, str], str | None] = {}
    modelspace = document.modelspace()
    known_layer_names = {layer.name.casefold(): layer.name for layer in layers.layers}
    for entity in modelspace:
        layer_name = str(entity.dxf.layer)
        values = _xdata_values(entity)
        if entity.dxftype() in ("DIMENSION", "ARC_DIMENSION"):
            if values and len(values) >= 1:
                known_sketch_ids.add(values[0])
            if len(values) >= 3 and values[1] == "dimension":
                try:
                    dimension_mappings.append((values[0], json.loads("".join(values[2:])), entity))
                except (TypeError, ValueError, json.JSONDecodeError):
                    warnings.append(f"DIMENSION {entity.dxf.handle} 的 MyCAD 标注数据无效，已跳过")
            else:
                warnings.append(
                    f"外部 DIMENSION {entity.dxf.handle} 没有关联的 MyCAD 图元引用，未导入其语义"
                )
            continue
        legacy_construction_layer = layer_name.upper() == _CONSTRUCTION_LAYER and len(values) < 5
        restored_layer_name = (
            "0" if legacy_construction_layer else known_layer_names.get(layer_name.casefold(), "0")
        )
        linetype = entity.dxf.get("linetype", "BYLAYER")
        non_default_linetype = isinstance(linetype, str) and linetype.upper() != "BYLAYER"
        if (
            entity.dxf.get("color", 256) != 256
            or non_default_linetype
            or entity.dxf.get("lineweight", -1) != -1
        ):
            warning = "实体级颜色、线型或线宽覆盖未保留"
            if warning not in warnings:
                warnings.append(warning)
        if values and len(values) >= 1:
            known_sketch_ids.add(values[0])
        entity_id = values[1] if len(values) >= 2 else uuid4().hex
        if not _is_identity(entity_id):
            entity_id = uuid4().hex
            warnings.append(f"无效的 MyCAD 图元 ID 已重新分配：{entity.dxf.handle}")
        semantic_kind = values[2] if len(values) >= 3 else ""
        sweep_sign = values[3] if len(values) >= 4 else "ccw"
        if entity_id in used_entity_ids:
            entity_id = uuid4().hex
            warnings.append(f"重复的 MyCAD 图元 ID 已重新分配：{entity.dxf.handle}")
        try:
            parsed = _read_entity(
                entity,
                entity_id,
                semantic_kind,
                sweep_sign,
                scale,
                restored_layer_name,
                values[4] == "1" if len(values) >= 5 else legacy_construction_layer,
            )
        except ValueError as exc:
            warnings.append(f"{entity.dxftype()} {entity.dxf.handle} 已跳过：{exc}")
            continue
        if parsed is None:
            warnings.append(
                f"{entity.dxftype()} {entity.dxf.handle}（图层 {entity.dxf.layer}）不在支持子集中，已跳过"
            )
            continue
        entities.append(parsed)
        used_entity_ids.add(entity_id)
        if len(values) >= 2 and _is_identity(values[0]) and _is_identity(values[1]):
            key = (values[0], values[1])
            entity_id_map[key] = None if key in entity_id_map else entity_id

    for layout_name in document.layout_names():
        if layout_name != "Model" and len(document.layouts.get(layout_name)):
            warnings.append(f"非模型空间布局 {layout_name} 未导入")
    if len(known_sketch_ids) > 1:
        warnings.append("文件包含多个 MyCAD 草图身份，导入时为图元合并创建新的草图身份")
        sketch_id = uuid4().hex
    else:
        sketch_id = next(iter(known_sketch_ids), uuid4().hex)
    if not _is_identity(sketch_id):
        sketch_id = uuid4().hex
        warnings.append("文件中的 MyCAD 草图身份无效，已重新分配")

    entity_ids = {entity.entity_id for entity in entities}
    measurement_sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), tuple(entities), layers=layers)
    constraints: list[SketchConstraint] = []
    imported_styles: list[tuple[str, DimensionStyle]] = []
    seen_constraint_ids: set[str] = set()
    seen_constraint_sources: set[tuple[str, str]] = set()
    for source_sketch_id, raw_constraint, native_dimension in dimension_mappings:
        refreshed_value = False
        native_warnings: list[str] = []
        imported_style: DimensionStyle | None = None
        try:
            constraint = SketchConstraint.from_mapping(raw_constraint)
            if constraint.kind not in (
                "length",
                "distance",
                "angle",
                "radius",
                "diameter",
                "arc_length",
            ):
                raise ValueError("关联类型不是尺寸")
            resolved = tuple(
                entity_id_map.get((source_sketch_id, ref.entity_id))
                for ref in constraint.references
            )
            if any(identity is None or identity not in entity_ids for identity in resolved):
                raise ValueError("标注引用的图元未能导入或身份不唯一")
            constraint = replace(
                constraint,
                references=tuple(
                    replace(ref, entity_id=cast("str", identity))
                    for ref, identity in zip(constraint.references, resolved, strict=True)
                ),
                value=(
                    constraint.value * scale
                    if constraint.value is not None and constraint.unit == "mm"
                    else constraint.value
                ),
                position_mm=(
                    None
                    if constraint.position_mm is None
                    else tuple(value * scale for value in constraint.position_mm)
                ),
                text_position_mm=(
                    None
                    if constraint.text_position_mm is None
                    else tuple(value * scale for value in constraint.text_position_mm)
                ),
            )
            try:
                native_changes = _dimension_snapshot_changes(native_dimension)
                if native_changes is None and _DIMENSION_SNAPSHOT_APPID in document.appids:
                    native_warnings.append("原生标注快照缺失，无法检查外部修改")
            except (TypeError, ValueError, json.JSONDecodeError):
                native_changes = None
                native_warnings.append("原生标注快照无效，无法检查外部修改")
            if native_changes:
                remaining_changes = set(native_changes)
                precision_key = "style:dimadec" if constraint.kind == "angle" else "style:dimdec"
                if precision_key in remaining_changes:
                    style = cast("_NativeDimension", native_dimension).override()
                    precision = style.get(precision_key.removeprefix("style:"))
                    rounding = style.get("dimrnd")
                    if (
                        isinstance(precision, int)
                        and not isinstance(precision, bool)
                        and 0 <= precision <= 8
                        and (
                            constraint.kind == "angle"
                            or not isinstance(rounding, int | float)
                            or rounding <= 0
                            or rounding <= 10.0**-precision
                        )
                    ):
                        constraint = replace(constraint, precision=precision)
                        remaining_changes.remove(precision_key)
                        native_warnings.append(
                            f"尺寸 {constraint.constraint_id[:8]} 的外部精度设置已恢复"
                        )
                if "text_midpoint" in remaining_changes and "extrusion" not in remaining_changes:
                    try:
                        position = _xy(native_dimension.dxf.get("text_midpoint"), scale)
                    except ValueError:
                        pass
                    else:
                        constraint = replace(constraint, text_position_mm=position)
                        remaining_changes.remove("text_midpoint")
                        native_warnings.append(
                            f"尺寸 {constraint.constraint_id[:8]} 的外部文字位置已恢复"
                        )
                if remaining_changes:
                    native_warnings.append(
                        f"尺寸 {constraint.constraint_id[:8]} 的原生标注已修改，部分修改未恢复"
                    )
            style_values = _xdata_values(native_dimension, _DIMENSION_STYLE_APPID)
            if style_values:
                try:
                    if len(style_values) < 3 or style_values[0] != "2":
                        raise ValueError("标注样式数据版本不受支持")
                    snapshot_values = _xdata_values(native_dimension, _DIMENSION_SNAPSHOT_APPID)
                    if (
                        not snapshot_values
                        or snapshot_values[0] not in ("3", "4", "5", "6", "7")
                        or native_changes is None
                        or any(name.startswith("style:") for name in native_changes)
                    ):
                        raise ValueError("原生样式已变化或无法核对")
                    style_payload = "".join(style_values[2:])
                    digest = hashlib.sha256(
                        ("".join(snapshot_values[1:]) + "\n" + style_payload).encode("utf-8")
                    ).hexdigest()
                    if digest != style_values[1]:
                        raise ValueError("标注样式数据与快照不一致")
                    candidate = DimensionStyle.from_mapping(json.loads(style_payload))
                    if snapshot_values[0] == "3":
                        native_style = cast("_NativeDimension", native_dimension).override()
                        if any(native_style.get(key, -2) != -2 for key in ("dimlwd", "dimlwe")):
                            raise ValueError("旧快照无法核对外部线宽变化")
                    if snapshot_values[0] in ("3", "4"):
                        native_style = cast("_NativeDimension", native_dimension).override()
                        if any(
                            native_style.get(key, "") not in (None, "")
                            for key in ("dimltype", "dimltex1", "dimltex2")
                        ):
                            raise ValueError("旧快照无法核对外部线型变化")
                    if snapshot_values[0] in ("3", "4", "5"):
                        native_style = cast("_NativeDimension", native_dimension).override()
                        if any(
                            native_style.get(key, 0) not in (None, 0)
                            for key in ("dimse1", "dimse2")
                        ):
                            raise ValueError("旧快照无法核对外部界线显隐变化")
                    if snapshot_values[0] in ("3", "4", "5", "6"):
                        native_style = cast("_NativeDimension", native_dimension).override()
                        if any(
                            native_style.get(key, 0) not in (None, 0)
                            for key in ("dimsd1", "dimsd2")
                        ):
                            raise ValueError("旧快照无法核对外部尺寸线显隐变化")
                    if scale != 1.0 or (candidate.precision, candidate.scale) != (
                        constraint.precision,
                        constraint.scale,
                    ):
                        raise ValueError("样式单位或尺寸格式不一致")
                    imported_style = candidate
                except (TypeError, ValueError, json.JSONDecodeError):
                    native_warnings.append("尺寸样式信息无法安全恢复")
            if constraint.value is not None:
                measured = _measure_imported_dimension(measurement_sketch, constraint)
                difference = (
                    abs((measured - constraint.value + 180.0) % 360.0 - 180.0)
                    if constraint.kind == "angle"
                    else abs(measured - constraint.value)
                )
                tolerance = (
                    1e-7
                    if constraint.kind == "angle"
                    else max(1e-7, max(abs(measured), abs(constraint.value)) * 1e-9)
                )
                if difference > tolerance:
                    if constraint.driving:
                        raise ValueError("驱动尺寸值与导入几何不一致")
                    constraint = replace(constraint, value=measured)
                    refreshed_value = True
            source_key = (source_sketch_id, constraint.constraint_id)
            if source_key in seen_constraint_sources:
                raise ValueError("同一草图的标注 ID 重复")
            if constraint.constraint_id in seen_constraint_ids:
                identity = uuid4().hex
                while identity in seen_constraint_ids:
                    identity = uuid4().hex
                constraint = replace(constraint, constraint_id=identity)
                warnings.append("不同草图的重复 MyCAD 标注 ID 已重新分配")
        except ValueError as exc:
            warnings.append(f"MyCAD 尺寸标注未恢复：{exc}")
            continue
        constraints.append(constraint)
        if imported_style is not None:
            imported_styles.append((constraint.constraint_id, imported_style))
        warnings.extend(native_warnings)
        if refreshed_value:
            warnings.append(f"参考尺寸 {constraint.constraint_id[:8]} 已按导入几何更新")
        seen_constraint_ids.add(constraint.constraint_id)
        seen_constraint_sources.add(source_key)

    sketch = Sketch(
        sketch_id,
        WorkPlaneFrame.xy(),
        tuple(entities),
        constraints=tuple(constraints),
        layers=layers,
    )
    if not entities:
        warnings.append("文件中没有可导入的受支持二维图元")
    report = DxfExchangeReport(
        "导入",
        document.dxfversion,
        unit_name,
        len(entities) + len(constraints),
        tuple(warnings),
    )
    return DxfSketchImport(sketch, report, tuple(imported_styles))


def _dxf_arc_angles(entity: ArcEntity) -> tuple[float, float]:
    if entity.sweep_angle_deg >= 0:
        start = entity.start_angle_deg
        end = start + entity.sweep_angle_deg
    else:
        start = entity.start_angle_deg + entity.sweep_angle_deg
        end = entity.start_angle_deg
    return start % 360.0, end % 360.0


def _unit_scale(raw_code: object, override: str | None) -> tuple[float, str]:
    if override is not None:
        name = override.strip().lower()
        if name not in _UNIT_TO_MM:
            choices = ", ".join(_UNIT_TO_MM)
            raise ValueError(f"unit_override must be one of: {choices}")
        return _UNIT_TO_MM[name], f"{name} (override)"
    code = raw_code if isinstance(raw_code, int) and not isinstance(raw_code, bool) else 0
    name = _INSUNITS_TO_NAME.get(code)
    if name is None:
        raise DxfUnitOverrideRequired("DXF 未声明已支持的线性单位；请显式提供 unit_override")
    return _UNIT_TO_MM[name], name


def _read_entity(
    entity: _DxfEntity,
    entity_id: str,
    semantic_kind: str,
    sweep_sign: str,
    scale: float,
    layer_name: str,
    construction: bool,
) -> SketchEntity | None:
    kind = entity.dxftype()
    if kind == "POINT":
        return PointEntity(entity_id, _xy(entity.dxf.location, scale), construction, layer_name)
    if kind in {"LWPOLYLINE", "CIRCLE", "ARC"} and not _is_world_xy_normal(entity.dxf.extrusion):
        raise ValueError("只支持位于全局 XY 平面的图元")
    if kind == "SPLINE":
        spline = cast("_Spline", entity)
        if spline.dxf.get("degree") != 3 or int(cast("int", spline.dxf.get("flags", 0))) & 3:
            raise ValueError("当前支持开放夹持三次均匀 B 样条；周期或闭合样条未导入。")
        if any(abs(weight - 1.0) > 1e-12 for weight in spline.weights):
            raise ValueError("当前不支持非单位权重的有理样条。")
        result = SplineEntity(
            entity_id,
            tuple(_xy(point, scale) for point in spline.control_points),
            construction,
            layer_name,
        )
        knots = tuple(float(value) for value in spline.knots)
        if len(knots) != len(result.knots) or knots[-1] <= knots[0]:
            raise ValueError("样条节点向量无效。")
        normalized = tuple((value - knots[0]) / (knots[-1] - knots[0]) for value in knots)
        if any(
            not math.isfinite(value) or abs(value - expected) > 1e-9
            for value, expected in zip(normalized, result.knots, strict=True)
        ):
            raise ValueError("当前不支持非均匀或非夹持样条节点；曲线未离散降级。")
        return result
    if kind == "LINE":
        start = _xy(entity.dxf.start, scale)
        end = _xy(entity.dxf.end, scale)
        return LineEntity(entity_id, start, end, construction, layer_name)
    if kind == "LWPOLYLINE":
        polyline = cast("_LwPolyline", entity)
        points = tuple(polyline.get_points("xyseb"))
        if len(points) < 2:
            raise ValueError("多段线至少需要两个顶点")
        if polyline.dxf.get("const_width", 0) != 0 or any(
            start_width != 0 or end_width != 0 for _, _, start_width, end_width, _ in points
        ):
            raise ValueError("当前不支持具有宽度的多段线；不会转换为中心线")
        normalized = tuple((float(x) * scale, float(y) * scale) for x, y, _, _, _ in points)
        elevation = polyline.dxf.elevation
        z = getattr(elevation, "z", elevation)
        if isinstance(z, bool) or not isinstance(z, int | float) or abs(float(z)) > 1e-7:
            raise ValueError("只支持位于 DXF XY 平面的多段线")
        closed = polyline.closed
        if not closed and points[-1][4] != 0:
            raise ValueError("开放多段线末尾的未使用 bulge 无法保留")
        bulges = tuple(float(item[4]) for item in (points if closed else points[:-1]))
        if (
            semantic_kind == "rectangle"
            and not any(bulges)
            and _is_rectangle_points(normalized, closed)
        ):
            xs = [point[0] for point in normalized]
            ys = [point[1] for point in normalized]
            return RectangleEntity(
                entity_id,
                (min(xs), min(ys)),
                (max(xs), max(ys)),
                construction,
                layer_name,
            )
        return PolylineEntity(entity_id, normalized, closed, construction, layer_name, bulges)
    if kind == "CIRCLE":
        center = _xy(entity.dxf.center, scale)
        return CircleEntity(
            entity_id, center, float(entity.dxf.radius) * scale, construction, layer_name
        )
    if kind == "ARC":
        center = _xy(entity.dxf.center, scale)
        start = float(entity.dxf.start_angle)
        end = float(entity.dxf.end_angle)
        sweep = (end - start) % 360.0
        if sweep <= 1e-12:
            raise ValueError("圆弧扫角必须大于 0 且小于 360 度")
        if sweep_sign == "cw":
            return ArcEntity(
                entity_id,
                center,
                float(entity.dxf.radius) * scale,
                end,
                -sweep,
                construction,
                layer_name,
            )
        return ArcEntity(
            entity_id,
            center,
            float(entity.dxf.radius) * scale,
            start,
            sweep,
            construction,
            layer_name,
        )
    return None


def _xy(value: object, scale: float) -> tuple[float, float]:
    try:
        x, y, z = cast("Sequence[float]", value)
    except (TypeError, ValueError) as exc:
        raise ValueError("图元坐标格式无效") from exc
    if not all(math.isfinite(component) for component in (x, y, z)):
        raise ValueError("图元坐标必须有限")
    if abs(z) > 1e-7:
        raise ValueError("只支持位于 DXF XY 平面的图元")
    return (float(x) * scale, float(y) * scale)


def _xdata_values(entity: _DxfEntity, appid: str = _APPID) -> tuple[str, ...]:
    try:
        tags = entity.get_xdata(appid)
    except DXFValueError:
        return ()
    return tuple(str(tag.value) for tag in tags if tag.code == 1000)


def _is_identity(value: str) -> bool:
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return value in {parsed.hex, str(parsed)}


def _is_world_xy_normal(value: object) -> bool:
    try:
        x, y, z = cast("Sequence[object]", value)
    except (TypeError, ValueError):
        return False
    if any(
        isinstance(component, bool) or not isinstance(component, int | float)
        for component in (x, y, z)
    ):
        return False
    x_value, y_value, z_value = (cast("int | float", component) for component in (x, y, z))
    return (
        abs(float(x_value)) <= 1e-9
        and abs(float(y_value)) <= 1e-9
        and abs(float(z_value) - 1.0) <= 1e-9
    )


def _is_rectangle_points(points: tuple[tuple[float, float], ...], closed: bool) -> bool:
    return (
        closed
        and len(points) == 4
        and len({point[0] for point in points}) == 2
        and len({point[1] for point in points}) == 2
        and all(
            points[index][0] == points[(index + 1) % 4][0]
            or points[index][1] == points[(index + 1) % 4][1]
            for index in range(4)
        )
    )


DXF_PROVIDER = DxfSketchProvider(
    name="DXF sketch subset",
    vendor="ezdxf",
    priority=100,
    extensions=(".dxf",),
    can_read=True,
    can_write=True,
    target="shape",
    _writer=_write_dxf,
)
