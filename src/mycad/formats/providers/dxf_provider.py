# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exchange the supported neutral sketch subset as 2D DXF R2010."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Iterator, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast, runtime_checkable
from uuid import UUID, uuid4

import ezdxf.filemanagement as _filemanagement
from ezdxf.colors import aci2rgb, int2rgb
from ezdxf.filemanagement import new as _new_dxf
from ezdxf.lldxf.const import DXFValueError

from mycad.core.exceptions import ValidationError
from mycad.core.ports import ExportableKernel
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
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


@runtime_checkable
class _SketchSource(Protocol):
    @property
    def sketches(self) -> tuple[Sketch, ...]:
        """Neutral sketches currently replayed into the kernel."""
        ...


class _DxfAttributes(Protocol):
    layer: str
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

    def render(self) -> object: ...

    def set_location(
        self, location: Sequence[float], leader: bool = False, relative: bool = False
    ) -> None: ...


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


def _write_dimension(modelspace: _Modelspace, sketch: Sketch, constraint: SketchConstraint) -> None:
    if constraint.kind not in ("length", "distance", "angle", "radius", "diameter", "arc_length"):
        raise ValueError("只支持长度、距离、角度、半径和直径标注")
    if constraint.value is None:
        raise ValueError("尺寸没有可显示的数值")
    first_reference = constraint.references[0]
    first_entity = _sketch_entity(sketch, first_reference)
    attributes: Mapping[str, object] = {"layer": constraint.layer_name or first_entity.layer_name}
    text = "<>" if constraint.kind == "angle" else "<> mm"
    override = _dimension_style(constraint)
    offset = max(5.0 * constraint.scale, 2.5 * constraint.scale)

    if constraint.kind in ("length", "distance"):
        if constraint.kind == "length":
            first, second = _dimension_line(sketch, first_reference)
        else:
            first = _dimension_point(sketch, first_reference)
            second = _dimension_point(sketch, constraint.references[1])
        if constraint.axis.startswith("ordinate_"):
            location = constraint.position_mm or (second[0] + offset, second[1] + offset)
            result = modelspace.add_ordinate_dim(
                feature_location=second,
                offset=(location[0] - second[0], location[1] - second[1]),
                dtype=1 if constraint.axis == "ordinate_x" else 0,
                origin=first,
                text=text,
                override=override,
                dxfattribs=attributes,
            )
        elif constraint.axis in ("horizontal", "vertical"):
            result = modelspace.add_linear_dim(
                base=constraint.position_mm or (first[0] + offset, first[1] + offset),
                p1=first,
                p2=second,
                angle=0.0 if constraint.axis == "horizontal" else 90.0,
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
        first_vector = (line1[1][0] - line1[0][0], line1[1][1] - line1[0][1])
        second_vector = (line2[1][0] - line2[0][0], line2[1][1] - line2[0][1])
        # Native three-point dimensions keep measured and rendered rays in
        # the same order. Two-line dimensions can render the complementary
        # sector even when get_measurement() reports the intended angle.
        if constraint.value < 0:
            first_vector, second_vector = second_vector, first_vector
            text = "-<>"
        start_angle = math.atan2(first_vector[1], first_vector[0])
        end_angle = math.atan2(second_vector[1], second_vector[0])
        sweep = (end_angle - start_angle) % math.tau
        middle_angle = start_angle + sweep / 2.0
        location = (
            vertex[0] + offset * math.cos(middle_angle),
            vertex[1] + offset * math.sin(middle_angle),
        )
        location = constraint.position_mm or location
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

    if constraint.text_position_mm is not None:
        result.set_location(constraint.text_position_mm, leader=True)
    result.render()
    payload = json.dumps(
        constraint.to_mapping(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    entity = result.dimension
    entity.set_xdata(
        _APPID,
        [(1000, sketch.sketch_id), (1000, "dimension")]
        + [(1000, payload[index : index + 240]) for index in range(0, len(payload), 240)],
    )


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
    if len(geometry.sketches) != 1:
        raise ValidationError(f"DXF 子集导出要求恰好一张草图，当前有 {len(geometry.sketches)} 张。")
    report = write_sketch_dxf(geometry.sketches[0], path)
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
    document = _new_r2010("R2010", units=4)
    document.header["$INSUNITS"] = 4
    document.header["$MEASUREMENT"] = 1
    document.appids.new(_APPID, dxfattribs=None)
    _write_layers(document, sketch.layers)
    modelspace = document.modelspace()
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
            dxf_entity = modelspace.add_lwpolyline(
                entity.points_mm, close=entity.closed, dxfattribs=attributes
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

    warnings: list[str] = []
    exported_dimensions = 0
    for constraint in sketch.constraints:
        try:
            _write_dimension(modelspace, sketch, constraint)
        except (TypeError, ValueError) as exc:
            warnings.append(f"尺寸/约束 {constraint.constraint_id[:8]} 未导出为 DXF 标注：{exc}")
        else:
            exported_dimensions += 1
    document.saveas(path)

    if not sketch.entities:
        warnings.append("草图中没有可导出的二维图元")
    if sketch.frame != WorkPlaneFrame.xy():
        warnings.append("工作平面位姿未写入 DXF，图元按草图局部坐标投影到 XY")
    return DxfExchangeReport(
        "导出",
        document.dxfversion,
        "mm",
        len(sketch.entities) + exported_dimensions,
        tuple(warnings),
    )


def read_sketch_dxf(path: Path, *, unit_override: str | None = None) -> DxfSketchImport:
    """Read 2D linework into one XY sketch; unsupported entities are reported."""
    document = _read_dxf_file(path)
    scale, unit_name = _unit_scale(document.header.get("$INSUNITS", 0), unit_override)
    warnings: list[str] = []
    layers = _read_layers(document, warnings)
    entities: list[SketchEntity] = []
    dimension_mappings: list[tuple[str, object]] = []
    known_sketch_ids: set[str] = set()
    used_entity_ids: set[str] = set()
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
                    dimension_mappings.append((values[0], json.loads("".join(values[2:]))))
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
    constraints: list[SketchConstraint] = []
    seen_constraint_ids: set[str] = set()
    for source_sketch_id, raw_constraint in dimension_mappings:
        if source_sketch_id != sketch_id:
            warnings.append("DXF 标注与导入草图身份不一致，已跳过")
            continue
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
            if any(reference.entity_id not in entity_ids for reference in constraint.references):
                raise ValueError("标注引用的图元未能导入")
            if constraint.constraint_id in seen_constraint_ids:
                raise ValueError("标注 ID 重复")
        except ValueError as exc:
            warnings.append(f"MyCAD 尺寸标注未恢复：{exc}")
            continue
        constraints.append(constraint)
        seen_constraint_ids.add(constraint.constraint_id)

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
    return DxfSketchImport(sketch, report)


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
        if any(bulge != 0 for _, _, _, _, bulge in points):
            raise ValueError("当前不支持带 bulge 圆弧段的多段线；不会转换为直线")
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
        if semantic_kind == "rectangle" and _is_rectangle_points(normalized, closed):
            xs = [point[0] for point in normalized]
            ys = [point[1] for point in normalized]
            return RectangleEntity(
                entity_id,
                (min(xs), min(ys)),
                (max(xs), max(ys)),
                construction,
                layer_name,
            )
        return PolylineEntity(entity_id, normalized, closed, construction, layer_name)
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


def _xdata_values(entity: _DxfEntity) -> tuple[str, ...]:
    try:
        tags = entity.get_xdata(_APPID)
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
