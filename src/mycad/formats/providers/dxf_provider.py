# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exchange the supported neutral sketch subset as 2D DXF R2010."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, cast, runtime_checkable
from uuid import UUID, uuid4

import ezdxf.filemanagement as _filemanagement
import ezdxf.render.arrows as _arrows
from ezdxf.colors import RGB, aci2rgb, int2rgb
from ezdxf.entities import Dimension
from ezdxf.entities.insert import Insert
from ezdxf.filemanagement import new as _new_dxf
from ezdxf.lldxf.const import DXFAttributeError, DXFTableEntryError, DXFValueError
from ezdxf.render.arrows import ARROWS
from ezdxf.xclip import XClip

from mycad.core.angular_dimension import angular_sector
from mycad.core.cross_sketch_tangency import (
    project_coplanar_vector,
    project_polyline_entity,
    project_tangent_entity,
)
from mycad.core.detached_dimension import DetachedDimension
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.dimension_tolerance import (
    DimensionTolerance,
    effective_tolerance,
    tolerance_values_hidden_by_precision,
)
from mycad.core.drawing_blocks import BlockDefinition, BlockInstance, expand_block
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable, move_text
from mycad.core.exceptions import ValidationError
from mycad.core.geometric_tolerance import (
    AnnotationAttachment,
    DatumAttachment,
    DatumIdentifier,
    DatumReference,
    FeatureControlFrame,
    SurfaceIndication,
    ToleranceRow,
)
from mycad.core.geometric_tolerance_attachment import (
    resolve_attachment_local,
    resolve_attachment_normal,
    resolve_datum_bar_direction,
)
from mycad.core.geometric_tolerance_geometry import (
    datum_leader_path,
    datum_triangle,
    frame_leader_arrow,
    surface_indication_geometry,
)
from mycad.core.geometric_tolerance_surface_extension import surface_extension_geometry
from mycad.core.geometric_tolerance_topology import new_curve_point_identities
from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.ports import ExportableKernel
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
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
from mycad.core.sketch_edit import move_entities
from mycad.core.sketch_layers import (
    DEFAULT_SKETCH_LAYER,
    STANDARD_LINEWEIGHTS_MM,
    SketchLayer,
    SketchLayerTable,
    SketchLinetype,
)
from mycad.core.text_interchange import reconcile_text_styles
from mycad.formats.base import FormatProvider
from mycad.formats.dxf_collections import (
    DxfObjectMap,
    collection_export_name,
    is_exact_positive_xy_normal,
    read_native_groups,
    unique_import_name,
    write_native_groups,
)
from mycad.formats.dxf_curve_identity import (
    CURVE_IDENTITY_APPID,
    CURVE_IDENTITY_MARKER,
    pack_curve_identities,
    restore_curve_identities,
)
from mycad.formats.dxf_datum import (
    DATUM_APPID,
    DatumNativeSnapshot,
    read_datum,
    read_datum_text_style,
    write_datum,
)
from mycad.formats.dxf_detached_dimension import (
    REFERENCE_DIMENSION_APPID,
    angular_dimension_graphics,
    angular_dimension_has_inspectable_arc,
    angular_graphic_omits_tolerance,
    angular_graphic_shows_only_nominal,
    angular_precision_in_degrees,
    angular_tolerance_factor_to_degrees,
    apply_dimension_main_text,
    apply_limit_text_affixes,
    correct_ordinate_limit_graphics,
    ordinate_axis_snapshot_warnings,
    read_detached_dimension,
    read_native_tolerance,
    write_detached_dimension,
)
from mycad.formats.dxf_units import scaled_length_precision
from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata
from mycad.formats.ellipse_exchange import ellipse_from_dxf, ellipse_to_dxf
from mycad.formats.geometric_tolerance_codec import (
    decode_rows,
    encode_rows,
    normalize_legacy_negative_zero,
)
from mycad.formats.text_exchange import (
    native_style_matches_snapshot,
    read_dxf_text_style,
    read_texts_dxf,
    write_texts_dxf,
)

_APPID = "MYCAD"
_DIMENSION_SNAPSHOT_APPID = "MYCAD_DIMENSION_SNAPSHOT"
_DIMENSION_STYLE_APPID = "MYCAD_DIMENSION_STYLE"
_FCF_APPID = "MYCAD_FCF"
_FCF_LEADER_APPID = "MYCAD_FCF_LEADER"
_SURFACE_EXTENSION_APPID = "MYCAD_SURFACE_EXT"
_SURFACE_INDICATION_APPID = "MYCAD_SURFACE_IND"
_FCF_DEFAULT_DIMSTYLE = "MYCAD_FCF_DEFAULT"
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
_DIMENSION_STYLE_V8_FIELDS = (
    *_DIMENSION_STYLE_V7_FIELDS,
    "dimtol",
    "dimlim",
    "dimtp",
    "dimtm",
    "dimtfac",
    "dimtdec",
    "dimtolj",
)
_DIMENSION_STYLE_DEFAULTS: dict[str, int | float | str] = {
    "dimclrt": 0,
    "dimclrd": 0,
    "dimclre": 0,
    "dimscale": 1.0,
    "dimrnd": 0.0,
    "dimpost": "",
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
    "dimtol": 0,
    "dimlim": 0,
    "dimtp": 0.0,
    "dimtm": 0.0,
    "dimtfac": 1.0,
    "dimtdec": 2,
    "dimtolj": 0,
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
    texts: tuple[DrawingText, ...] = ()
    text_styles: TextStyleTable | None = None
    tolerance_frames: tuple[FeatureControlFrame, ...] = ()
    datum_identifiers: tuple[DatumIdentifier, ...] = ()
    detached_dimensions: tuple[DetachedDimension, ...] = ()
    groups: tuple[DrawingGroup, ...] = ()
    block_definitions: tuple[BlockDefinition, ...] = ()
    block_instances: tuple[BlockInstance, ...] = ()


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
class _TextSource(Protocol):
    @property
    def drawing_texts(self) -> tuple[DrawingText, ...]: ...

    @property
    def drawing_text_styles(self) -> TextStyleTable: ...


@runtime_checkable
class _ReferenceDimensionSource(Protocol):
    @property
    def drawing_reference_dimensions(self) -> tuple[DetachedDimension, ...]: ...


@runtime_checkable
class _DrawingLayerSource(Protocol):
    @property
    def drawing_layers(self) -> SketchLayerTable: ...


@runtime_checkable
class _DrawingGroupSource(Protocol):
    @property
    def drawing_groups(self) -> tuple[DrawingGroup, ...]: ...


@runtime_checkable
class _DrawingBlockSource(Protocol):
    @property
    def drawing_block_definitions(self) -> tuple[BlockDefinition, ...]: ...

    @property
    def drawing_block_instances(self) -> tuple[BlockInstance, ...]: ...


@runtime_checkable
class _ToleranceSource(Protocol):
    @property
    def drawing_tolerance_frames(self) -> tuple[FeatureControlFrame, ...]: ...

    @property
    def drawing_datum_identifiers(self) -> tuple[DatumIdentifier, ...]: ...


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
    dimasz: float
    horizontal_direction: float
    location: Sequence[float]
    start: Sequence[float]
    end: Sequence[float]
    center: Sequence[float]
    major_axis: Sequence[float]
    ratio: float
    start_param: float
    end_param: float
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

    def hasattr(self, name: str) -> bool: ...

    def unprotected_set(self, name: str, value: object) -> None: ...


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


class _LegacyPolyline(_DxfEntity, Protocol):
    vertices: Sequence[_DxfEntity]
    is_2d_polyline: bool
    is_closed: bool


class _Spline(_DxfEntity, Protocol):
    control_points: Sequence[Sequence[float]]
    knots: Sequence[float]
    weights: Sequence[float]


class _Leader(_DxfEntity, Protocol):
    vertices: Sequence[Sequence[float]]

    def override(self) -> _NativeDimensionStyle: ...


class _Insert(_DxfEntity, Protocol):
    attribs: Sequence[object]

    def virtual_entities(
        self, *, skipped_entity_callback: Callable[[_DxfEntity, str], None] | None = None
    ) -> Iterator[_DxfEntity]: ...


class _Modelspace(Protocol):
    def add_blockref(
        self, name: str, insert: Sequence[float], *, dxfattribs: Mapping[str, object]
    ) -> _DxfEntity: ...
    def new_entity(self, type_: str, dxfattribs: dict[str, object]) -> _DxfEntity: ...

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

    def query(self, query: str) -> Iterable[_DxfEntity]: ...

    def add_leader(
        self,
        vertices: Sequence[Sequence[float]],
        *,
        dimstyle: str,
        dxfattribs: Mapping[str, object],
    ) -> _Leader: ...

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

    def add_ellipse(
        self,
        center: Sequence[float],
        major_axis: Sequence[float],
        ratio: float,
        start_param: float,
        end_param: float,
        *,
        dxfattribs: Mapping[str, object],
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
    entity: _DxfEntity, *, include_style: bool = True, version: int = 8
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
            _DIMENSION_STYLE_V8_FIELDS
            if version >= 8
            else _DIMENSION_STYLE_V7_FIELDS
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
    if values[0] not in ("1", "2", "3", "4", "5", "6", "7", "8"):
        raise ValueError("原生标注快照版本不受支持")
    raw_previous: object = json.loads("".join(values[1:]))
    if not isinstance(raw_previous, dict):
        raise ValueError("原生标注快照无效")
    previous = cast("dict[str, object]", raw_previous)
    expected_fields: set[str] = set(_DIMENSION_SNAPSHOT_FIELDS)
    if values[0] in ("2", "3", "4", "5", "6", "7", "8"):
        fields = (
            _DIMENSION_STYLE_V8_FIELDS
            if values[0] == "8"
            else _DIMENSION_STYLE_V7_FIELDS
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
        if (
            name == "defpoint5"
            and value is None
            and entity.dxftype() == "DIMENSION"
            and cast("int", entity.dxf.get("dimtype", 0)) & 15 == 5
        ):
            return (0.0, 0.0, 0.0)
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
        if not (
            normalized(name, previous[name]) == normalized(name, current[name])
            if name in {"style:dimtp", "style:dimtm", "style:dimtfac"}
            else same(normalized(name, previous[name]), normalized(name, current[name]))
        )
    )


class _NamedTable(Protocol):
    def __contains__(self, name: object) -> bool: ...

    def new(self, name: str, *, dxfattribs: Mapping[str, object] | None = None) -> object: ...


class _DimstyleTable(_NamedTable, Protocol):
    def get(self, name: str) -> _DxfEntity: ...

    def duplicate_entry(self, name: str, new_name: str) -> _DxfEntity: ...


class _LayerInfo(Protocol):
    dxf: _DxfLayerAttributes
    transparency: float

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


class _BlockLayouts(Protocol):
    def __iter__(self) -> Iterator[_BlockLayout]: ...

    def __contains__(self, name: str) -> bool: ...

    def new(self, name: str, base_point: Sequence[float]) -> _Modelspace: ...

    def get(self, name: str) -> _BlockLayout | None: ...


class _ExtensionDictionary(Protocol):
    def __contains__(self, key: str) -> bool: ...


class _BlockRecord(Protocol):
    @property
    def has_extension_dict(self) -> bool: ...

    def get_extension_dict(self) -> _ExtensionDictionary: ...


class _BlockLayout(_Modelspace, Protocol):
    name: str
    block: _DxfEntity
    block_record: _BlockRecord


class _Drawing(Protocol):
    header: MutableMapping[str, object]
    appids: _NamedTable
    dimstyles: _DimstyleTable
    layers: _LayerTable
    linetypes: _LinetypeTable
    layouts: _LayoutTable
    blocks: _BlockLayouts
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
            "linetype": _DXF_LINETYPE_NAMES[layer.linetype],
            "lineweight": round(layer.lineweight_mm * 100.0),
        }
        if layer.color_rgb != DEFAULT_SKETCH_LAYER.color_rgb:
            attributes["true_color"] = color
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
    text_style_names: Mapping[str, str] | None = None,
) -> str:
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
    limit_text = text
    if constraint.text_override is None:
        limit_text = {"radius": "R", "diameter": "⌀", "arc_length": "⌒"}.get(
            constraint.kind, ""
        ) + text
        if constraint.kind == "angle":
            limit_text += "°"
    if not constraint.driving:
        limit_text = f"({limit_text})"
    override = _dimension_style(constraint)
    default_tolerance = (
        DimensionTolerance()
        if drawing_style is None
        else (
            drawing_style.angular_tolerance
            if constraint.kind == "angle"
            else drawing_style.linear_tolerance
        )
    )
    tolerance = effective_tolerance(default_tolerance, constraint.tolerance)
    if tolerance.mode == "limits":
        try:
            tolerance.limits(constraint.value)
        except ValueError as exc:
            raise ValueError("公差极限超出范围") from exc
    if tolerance_values_hidden_by_precision(constraint.value, tolerance):
        raise ValueError("公差精度不足，非零偏差将显示为零或不同的上下偏差、极限显示相同")
    if tolerance.mode != "none":
        if constraint.text_override is not None and constraint.text_override.count("<>") != 1:
            raise ValueError("启用公差的尺寸文字需要一个 <> 占位符")
        override.update(
            {
                "dimtol": int(tolerance.mode in ("deviation", "symmetric")),
                "dimlim": int(tolerance.mode == "limits"),
                "dimtp": tolerance.upper_deviation,
                "dimtm": -tolerance.lower_deviation,
                "dimtfac": tolerance.text_factor,
                "dimtdec": tolerance.precision,
                "dimtolj": {"bottom": 0, "middle": 1, "top": 2}[tolerance.alignment],
            }
        )
    if drawing_style is not None:
        if drawing_style.text_style_id is not None and text_style_names is not None:
            native_style_name = text_style_names.get(drawing_style.text_style_id)
            if native_style_name is not None:
                override["dimtxsty"] = native_style_name
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
        renderer = result.render()
        if (
            constraint.axis.startswith("ordinate_")
            and constraint.value < 0
            and tolerance.mode == "limits"
        ):
            correct_ordinate_limit_graphics(renderer, constraint.value)
        if tolerance.mode == "limits":
            apply_limit_text_affixes(renderer, limit_text, angular=constraint.kind == "angle")
        elif not constraint.driving or constraint.text_override is not None:
            apply_dimension_main_text(
                renderer,
                reference=not constraint.driving,
                kind=constraint.kind,
                template=text if constraint.text_override is not None else None,
            )
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
            return result.dimension.dxf.handle
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
            [(1000, "8")]
            + [(1000, snapshot[index : index + 240]) for index in range(0, len(snapshot), 240)],
        )
        if drawing_style is not None:
            portable_style = drawing_style
            if drawing_style.text_style_id is not None and (
                text_style_names is None or drawing_style.text_style_id not in text_style_names
            ):
                portable_style = replace(drawing_style, text_style_id=None)
            style_payload = json.dumps(
                portable_style.to_mapping(),
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
    return result.dimension.dxf.handle


def _read_layers(
    document: _Drawing, warnings: list[str]
) -> tuple[SketchLayerTable, dict[str, str]]:
    result = SketchLayerTable()
    known_names = {"0"}
    native_names = {"0": "0"}
    for info in document.layers:
        raw_name = info.dxf.get("name", "")
        if not isinstance(raw_name, str):
            warnings.append("DXF 含无效图层名称，已忽略该图层定义")
            continue
        if raw_name.lower() == "0":
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
            name = unique_import_name(raw_name, known_names, max_length=255)
            if name != raw_name:
                layer = replace(layer, name=name)
            result = result.add(layer)
        except ValueError as exc:
            warnings.append(f"DXF 图层 {raw_name!r} 未能保留：{exc}")
            continue
        known_names.add(name.casefold())
        native_names[raw_name.lower()] = name
        if name != raw_name:
            warnings.append(f"图层名称冲突：{raw_name} → {name}。")
    return result, native_names


def _read_layer_info(info: _LayerInfo, warnings: list[str]) -> SketchLayer:
    raw_name = info.dxf.get("name", "")
    name = raw_name if isinstance(raw_name, str) else ""
    if info.transparency > 0:
        warnings.append(f"DXF 图层 {name} 的透明度不受支持，已按不透明导入")
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
        rgb = RGB(*DEFAULT_SKETCH_LAYER.color_rgb) if color_index == 7 else aci2rgb(color_index)

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


def write_dxf_graphics_intermediate(
    geometry: ExportableKernel,
    path: Path,
    *,
    legacy_frame_anchors: Mapping[str, tuple[float, float]] | None = None,
    legacy_frame_skipped_vertices: Mapping[str, int] | None = None,
    legacy_frame_bounds: Mapping[str, tuple[float, float, float, float]] | None = None,
) -> DxfExchangeReport:
    """Write a temporary DXF that must be converted before it is delivered."""
    return _write_dxf(
        geometry,
        path,
        _allow_long_tolerance=True,
        legacy_frame_anchors=legacy_frame_anchors,
        legacy_frame_skipped_vertices=legacy_frame_skipped_vertices,
        legacy_frame_bounds=legacy_frame_bounds,
    )


def write_dxf_with_frame_anchors(
    geometry: ExportableKernel,
    path: Path,
    legacy_frame_anchors: Mapping[str, tuple[float, float]],
    legacy_frame_skipped_vertices: Mapping[str, int] | None = None,
    legacy_frame_bounds: Mapping[str, tuple[float, float, float, float]] | None = None,
    *,
    legacy_datum_snapshots: Mapping[str, DatumNativeSnapshot] | None = None,
) -> DxfExchangeReport:
    """Write DXF with explicit legacy anchors from a UI layout snapshot."""
    return _write_dxf(
        geometry,
        path,
        legacy_frame_anchors=legacy_frame_anchors,
        legacy_frame_skipped_vertices=legacy_frame_skipped_vertices,
        legacy_frame_bounds=legacy_frame_bounds,
        legacy_datum_snapshots=legacy_datum_snapshots,
    )


def _write_dxf(
    geometry: ExportableKernel,
    path: Path,
    *,
    _allow_long_tolerance: bool = False,
    legacy_frame_anchors: Mapping[str, tuple[float, float]] | None = None,
    legacy_frame_skipped_vertices: Mapping[str, int] | None = None,
    legacy_frame_bounds: Mapping[str, tuple[float, float, float, float]] | None = None,
    legacy_datum_snapshots: Mapping[str, DatumNativeSnapshot] | None = None,
) -> DxfExchangeReport:
    if not isinstance(geometry, _SketchSource):
        raise ValidationError("DXF 导出需要提供草图数据的几何内核。")
    styles = (
        geometry.drawing_dimension_styles if isinstance(geometry, _DimensionStyleSource) else None
    )
    report = write_sketches_dxf(
        geometry.sketches,
        path,
        dimension_styles=styles,
        texts=geometry.drawing_texts if isinstance(geometry, _TextSource) else (),
        text_styles=geometry.drawing_text_styles if isinstance(geometry, _TextSource) else None,
        tolerance_frames=geometry.drawing_tolerance_frames
        if isinstance(geometry, _ToleranceSource)
        else (),
        drawing_layers=geometry.drawing_layers
        if isinstance(geometry, _DrawingLayerSource)
        else None,
        datum_identifiers=geometry.drawing_datum_identifiers
        if isinstance(geometry, _ToleranceSource)
        else (),
        reference_dimensions=geometry.drawing_reference_dimensions
        if isinstance(geometry, _ReferenceDimensionSource)
        else (),
        groups=geometry.drawing_groups if isinstance(geometry, _DrawingGroupSource) else (),
        block_definitions=geometry.drawing_block_definitions
        if isinstance(geometry, _DrawingBlockSource)
        else (),
        block_instances=geometry.drawing_block_instances
        if isinstance(geometry, _DrawingBlockSource)
        else (),
        _allow_long_tolerance=_allow_long_tolerance,
        legacy_frame_anchors=legacy_frame_anchors,
        legacy_frame_skipped_vertices=legacy_frame_skipped_vertices,
        legacy_frame_bounds=legacy_frame_bounds,
        legacy_datum_snapshots=legacy_datum_snapshots,
    )
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
        elif isinstance(entity, EllipseEntity):
            center = project(entity.center_mm)
            angle = math.radians(entity.rotation_deg)
            direction = project(
                (entity.center_mm[0] + math.cos(angle), entity.center_mm[1] + math.sin(angle))
            )
            rotation = math.degrees(math.atan2(direction[1] - center[1], direction[0] - center[0]))
            entities.append(
                replace(
                    entity,
                    center_mm=center,
                    rotation_deg=rotation,
                    start_angle_deg=entity.start_angle_deg
                    if normal_dot > 0
                    else -entity.start_angle_deg,
                    sweep_angle_deg=entity.sweep_angle_deg
                    if normal_dot > 0
                    else -entity.sweep_angle_deg,
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
        elif isinstance(entity, EllipseEntity):
            maximum = max(
                maximum, distance(entity.center_mm) + entity.major_radius_mm * math.hypot(u, v)
            )
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


def _surface_indication_dxf_parts(
    target: Point2D, indication: SurfaceIndication, *, arrow_size: float = 2.5
) -> tuple[tuple[str, Mapping[str, object]], ...]:
    reference, leader, _ = surface_indication_geometry(target, indication)
    triangle = datum_triangle(
        leader[-2],
        leader[-1],
        min(indication.arrow_size_mm or arrow_size, math.dist(leader[-2], leader[-1])),
    )
    if not triangle:
        raise ValueError("表面指示线末段长度为零")
    segments = (reference, *zip(leader, leader[1:], strict=False))
    lines = tuple(("LINE", {"start": (*a, 0.0), "end": (*b, 0.0)}) for a, b in segments)
    solid = ("SOLID", {f"vtx{index}": (*triangle[min(index, 2)], 0.0) for index in range(4)})
    return (*lines, solid)


def _scaled_surface_indication(indication: SurfaceIndication, scale: float) -> SurfaceIndication:
    start, end = indication.reference_start_offset_mm, indication.reference_end_offset_mm
    return replace(
        indication,
        reference_start_offset_mm=(start[0] * scale, start[1] * scale),
        reference_end_offset_mm=(end[0] * scale, end[1] * scale),
        leader_offsets_mm=tuple((x * scale, y * scale) for x, y in indication.leader_offsets_mm),
        arrow_size_mm=(
            indication.arrow_size_mm * scale if indication.arrow_size_mm is not None else None
        ),
    )


def _surface_extension_dxf_geometry(
    attachment: DatumAttachment, entity: SketchEntity
) -> tuple[str, dict[str, object], Point2D]:
    spec = attachment.surface_extension
    if spec is None or not isinstance(entity, LineEntity | ArcEntity):
        raise ValueError("表面延伸附着目标不是直线或圆弧")
    geometry = surface_extension_geometry(
        entity, spec.side, spec.distance_mm, spec.offset_mm, spec.overshoot_mm
    )
    if geometry.center_mm is None:
        return (
            "LINE",
            {"start": (*geometry.start_mm, 0.0), "end": (*geometry.end_mm, 0.0)},
            geometry.target_mm,
        )
    center = geometry.center_mm
    first = (
        math.degrees(math.atan2(geometry.start_mm[1] - center[1], geometry.start_mm[0] - center[0]))
        % 360
    )
    last = (first + geometry.sweep_angle_deg) % 360
    start, end = (first, last) if geometry.sweep_angle_deg > 0 else (last, first)
    return (
        "ARC",
        {
            "center": (*center, 0.0),
            "radius": math.dist(center, geometry.start_mm),
            "start_angle": start,
            "end_angle": end,
        },
        geometry.target_mm,
    )


def _surface_extension_matches(
    entity: _DxfEntity, kind: str, expected: dict[str, object], scale: float
) -> bool:
    if entity.dxftype() != kind:
        return False
    try:
        normal = cast("Sequence[float]", entity.dxf.get("extrusion", (0, 0, 1)))
        if (
            not all(math.isfinite(component) for component in normal)
            or math.dist(normal, (0, 0, 1)) > 1e-9
        ):
            return False
        points = ("start", "end") if kind == "LINE" else ("center",)
        if any(
            math.dist(_xy(entity.dxf.get(key), scale), _xy(expected[key], 1.0)) > 1e-7
            for key in points
        ):
            return False
        if kind == "ARC":
            radius = float(cast("float", entity.dxf.get("radius", 0))) * scale
            if not math.isclose(
                radius, cast("float", expected["radius"]), rel_tol=0.0, abs_tol=1e-7
            ):
                return False
            for key in ("start_angle", "end_angle"):
                actual = float(cast("float", entity.dxf.get(key, 0)))
                if (
                    not math.isfinite(actual)
                    or abs(math.remainder(actual - cast("float", expected[key]), 360)) > 1e-7
                ):
                    return False
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _surface_indication_component_matches(
    entity: _DxfEntity, kind: str, expected: Mapping[str, object], scale: float
) -> bool:
    if kind == "LINE":
        return _surface_extension_matches(entity, kind, dict(expected), scale)
    if entity.dxftype() != "SOLID":
        return False
    try:
        normal = cast("Sequence[float]", entity.dxf.get("extrusion", (0, 0, 1)))
        return (
            all(math.isfinite(value) for value in normal)
            and math.dist(normal, (0, 0, 1)) <= 1e-9
            and all(
                math.dist(
                    _xy(entity.dxf.get(f"vtx{index}"), scale), _xy(expected[f"vtx{index}"], 1.0)
                )
                <= 1e-7
                for index in range(4)
            )
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _legacy_hidden_vertices_in_symbol(
    frame: FeatureControlFrame, count: int, text_height: float
) -> bool:
    """Prove hidden points are inside the font-independent symbol cell."""
    scale = text_height / 3.5
    angle = math.radians(frame.rotation_deg)
    cosine, sine = math.cos(angle), math.sin(angle)
    return all(
        -1e-9 <= cosine * x + sine * y <= 5.4 * scale + 1e-9
        and -1e-9 <= sine * x - cosine * y <= 6.0 * len(frame.rows) * scale + 1e-9
        for x, y in frame.leader_offsets[:count]
    )


def _legacy_frame_layout_matches(
    frame: FeatureControlFrame,
    bounds: object,
    anchor: tuple[float, float],
    count: int,
    text_height: float,
) -> bool:
    """Check a saved frame rectangle against its complete visible leader path."""
    if not isinstance(bounds, list | tuple):
        return False
    values = cast("Sequence[object]", bounds)
    if len(values) != 4:
        return False
    if any(isinstance(value, bool) or not isinstance(value, int | float) for value in values):
        return False
    try:
        left, top, right, bottom = (float(cast("float", value)) for value in values)
        scale = text_height / 3.5
        if (
            not all(math.isfinite(value) for value in (left, top, right, bottom))
            or abs(left) > 1e-9
            or abs(top) > 1e-9
            or right < 7.0 * scale - 1e-9
            or not math.isclose(bottom, 6.0 * len(frame.rows) * scale, abs_tol=1e-9)
            or frame.leader_target_mm is None
        ):
            return False
        angle = math.radians(frame.rotation_deg)
        cosine, sine = math.cos(angle), math.sin(angle)

        def local_offset(x: float, y: float) -> tuple[float, float]:
            return cosine * x + sine * y, sine * x - cosine * y

        vertices = tuple(local_offset(x, y) for x, y in frame.leader_offsets)
        target = frame.leader_target_mm
        if frame.surface_indication is not None:
            _, _, target = surface_indication_geometry(target, frame.surface_indication)
        tx = target[0] - frame.position_mm[0]
        ty = target[1] - frame.position_mm[1]
        path = datum_leader_path((left, top, right, bottom), local_offset(tx, ty), vertices)
        if not path or len(vertices) + 2 - len(path) != count:
            return False
        x, y = path[0]
        expected = (cosine * x + sine * y, sine * x - cosine * y)
        return math.dist(expected, anchor) <= 1e-7
    except (TypeError, ValueError, OverflowError):
        return False


def write_sketches_dxf(
    sketches: tuple[Sketch, ...],
    path: Path,
    *,
    dimension_styles: DimensionStyleTable | None = None,
    texts: tuple[DrawingText, ...] = (),
    text_styles: TextStyleTable | None = None,
    tolerance_frames: tuple[FeatureControlFrame, ...] = (),
    drawing_layers: SketchLayerTable | None = None,
    datum_identifiers: tuple[DatumIdentifier, ...] = (),
    reference_dimensions: tuple[DetachedDimension, ...] = (),
    groups: tuple[DrawingGroup, ...] = (),
    block_definitions: tuple[BlockDefinition, ...] = (),
    block_instances: tuple[BlockInstance, ...] = (),
    object_map: DxfObjectMap | None = None,
    _allow_long_tolerance: bool = False,
    legacy_frame_anchors: Mapping[str, tuple[float, float]] | None = None,
    legacy_frame_skipped_vertices: Mapping[str, int] | None = None,
    legacy_frame_bounds: Mapping[str, tuple[float, float, float, float]] | None = None,
    legacy_datum_snapshots: Mapping[str, DatumNativeSnapshot] | None = None,
) -> DxfExchangeReport:
    """Write coplanar sketch geometry without merging source identities."""
    legacy_datums = {
        datum.datum_id: datum for datum in datum_identifiers if datum.layout_mode == "legacy"
    }
    if legacy_datum_snapshots is not None:
        if len({datum.datum_id for datum in datum_identifiers}) != len(datum_identifiers) or set(
            legacy_datum_snapshots
        ) != set(legacy_datums):
            raise ValidationError("旧基准布局快照与导出对象不匹配。")
        for identity, snapshot in legacy_datum_snapshots.items():
            if (
                snapshot.datum != legacy_datums[identity]
                or isinstance(snapshot.width, bool)
                or isinstance(snapshot.height, bool)
                or not isinstance(cast("object", snapshot.width), int | float)
                or not isinstance(cast("object", snapshot.height), int | float)
                or not math.isfinite(snapshot.width)
                or not math.isfinite(snapshot.height)
                or snapshot.width <= 0
                or snapshot.height <= 0
                or (
                    snapshot.datum.box_size_mm is not None
                    and math.dist((snapshot.width, snapshot.height), snapshot.datum.box_size_mm)
                    > 1e-9
                )
            ):
                raise ValidationError("旧基准布局快照无效或已过期。")
    anchors = legacy_frame_anchors or {}
    skipped = legacy_frame_skipped_vertices or {}
    bounds = legacy_frame_bounds or {}
    eligible = {
        frame.frame_id
        for frame in tolerance_frames
        if frame.leader_target_mm is not None and frame.leader_anchor_offset is None
    }
    if set(anchors) - eligible:
        raise ValidationError("旧公差框引线锚点与导出对象不匹配。")
    if set(skipped) - set(anchors):
        raise ValidationError("旧公差框隐藏顶点与导出锚点不匹配。")
    if set(bounds) - set(anchors):
        raise ValidationError("旧公差框布局范围与导出锚点不匹配。")
    for frame in tolerance_frames:
        count = cast("object", skipped.get(frame.frame_id, 0))
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 0 <= count <= len(frame.leader_offsets)
        ):
            raise ValidationError("旧公差框隐藏顶点数量无效。")
        if (
            count
            and frame.leader_auto_normal
            and count == len(frame.leader_offsets)
            and frame.frame_id not in bounds
        ):
            raise ValidationError("旧公差框隐藏顶点具有自动约束，无法安全导出。")
    legacy_normals = {
        frame.frame_id: frame
        for frame in tolerance_frames
        if frame.leader_auto_normal
        and skipped.get(frame.frame_id, 0) == len(frame.leader_offsets)
        and skipped.get(frame.frame_id, 0) > 0
    }
    legacy_routes = {
        frame.frame_id: frame
        for frame in tolerance_frames
        if frame.leader_auto_route
        and skipped.get(frame.frame_id, 0)
        and frame.frame_id not in legacy_normals
    }
    for frame in tolerance_frames:
        if frame.frame_id not in bounds and frame.frame_id not in legacy_routes:
            continue
        try:
            height = (
                text_styles.get(frame.text_style_id).height_mm
                if text_styles is not None and frame.text_style_id is not None
                else 3.5
            )
        except KeyError as exc:
            raise ValidationError("旧公差框文字样式不可用，无法验证隐藏顶点。") from exc
        matching = (
            _legacy_frame_layout_matches(
                frame,
                bounds[frame.frame_id],
                anchors[frame.frame_id],
                skipped.get(frame.frame_id, 0),
                height,
            )
            if frame.frame_id in bounds
            else _legacy_hidden_vertices_in_symbol(frame, skipped.get(frame.frame_id, 0), height)
        )
        if not matching:
            raise ValidationError("旧公差框布局锚点或隐藏顶点无法安全核验，请先调整引线。")
    try:
        tolerance_frames = tuple(
            replace(
                frame,
                leader_anchor_offset=anchors[frame.frame_id],
                leader_offsets=frame.leader_offsets[skipped.get(frame.frame_id, 0) :],
                leader_auto_normal=frame.leader_auto_normal
                and frame.frame_id not in legacy_normals,
                **(
                    {
                        "leader_auto_route": False,
                        "route_avoid_crossing": False,
                        "route_track_target": False,
                        "route_algorithm_version": 1,
                    }
                    if frame.frame_id in legacy_routes or frame.frame_id in legacy_normals
                    else {}
                ),
            )
            if frame.frame_id in anchors
            else frame
            for frame in tolerance_frames
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError("旧公差框引线锚点无效。") from exc
    annotations = [
        (datum.annotation_attachment, datum.target_mm) for datum in datum_identifiers
    ] + [(frame.leader_annotation_attachment, frame.leader_target_mm) for frame in tolerance_frames]
    for attachment, target_point in annotations:
        if attachment is None:
            continue
        x, y = attachment.offset_mm
        if attachment.kind == "frame":
            targets = [
                frame for frame in tolerance_frames if frame.frame_id == attachment.object_id
            ]
            if len(targets) != 1:
                raise ValidationError("标注附着目标无法安全导出 DXF。")
            frame = targets[0]
            angle = math.radians(frame.rotation_deg)
            point = (
                frame.position_mm[0] + x * math.cos(angle) - y * math.sin(angle),
                frame.position_mm[1] + x * math.sin(angle) + y * math.cos(angle),
            )
        elif attachment.kind == "reference_dimension":
            dimensions = [
                item for item in reference_dimensions if item.dimension_id == attachment.object_id
            ]
            if len(dimensions) != 1:
                raise ValidationError("标注附着目标无法安全导出 DXF。")
            point = (dimensions[0].location_mm[0] + x, dimensions[0].location_mm[1] + y)
        elif attachment.kind == "sketch_dimension":
            matches = [
                (sketch, constraint)
                for sketch in sketches
                if sketch.sketch_id == attachment.sketch_id
                for constraint in sketch.constraints
                if constraint.constraint_id == attachment.object_id
                and constraint.kind
                in ("length", "distance", "angle", "radius", "diameter", "arc_length")
            ]
            if len(matches) != 1:
                raise ValidationError("标注附着目标无法安全导出 DXF。")
            source, dimension = matches[0]
            anchor = (
                dimension.text_position_mm
                if attachment.anchor == "text" and dimension.text_position_mm is not None
                else dimension.position_mm
            )
            if anchor is None:
                raise ValidationError("标注附着的尺寸位置不可用，无法导出 DXF。")
            world = source.frame.local_to_world((anchor[0] + x, anchor[1] + y))
            point = (world[0], world[1])
        else:
            raise ValidationError("标注附着目标无法安全导出 DXF。")
        if target_point is None or math.dist(point, target_point) > 1e-7:
            raise ValidationError("标注附着目标位置不一致，无法安全导出 DXF。")
    frame_map = {frame.frame_id: frame for frame in tolerance_frames}
    for frame in tolerance_frames:
        visited: set[str] = set()
        current = frame
        while current.leader_annotation_attachment is not None:
            if current.leader_annotation_attachment.kind != "frame":
                break
            if current.frame_id in visited:
                raise ValidationError("公差框标注附着存在循环，无法导出 DXF。")
            visited.add(current.frame_id)
            current = frame_map[current.leader_annotation_attachment.object_id]

    def projected_annotation(
        attachment: AnnotationAttachment | None,
    ) -> AnnotationAttachment | None:
        if attachment is None or attachment.kind != "sketch_dimension":
            return attachment
        source = next(sketch for sketch in sketches if sketch.sketch_id == attachment.sketch_id)
        x, y = attachment.offset_mm
        return replace(
            attachment,
            offset_mm=(
                x * source.frame.u_axis[0] + y * source.frame.v_axis[0],
                x * source.frame.u_axis[1] + y * source.frame.v_axis[1],
            ),
        )

    datum_identifiers = tuple(
        replace(datum, annotation_attachment=projected_annotation(datum.annotation_attachment))
        for datum in datum_identifiers
    )
    tolerance_frames = tuple(
        replace(
            frame,
            leader_annotation_attachment=projected_annotation(frame.leader_annotation_attachment),
        )
        for frame in tolerance_frames
    )
    if (
        not sketches
        and not texts
        and not tolerance_frames
        and not datum_identifiers
        and not reference_dimensions
        and not block_definitions
        and not block_instances
    ):
        raise ValidationError("DXF 导出至少需要一张草图、文字或形位公差对象。")
    if len({sketch.sketch_id for sketch in sketches}) != len(sketches):
        raise ValidationError("DXF 导出的草图身份不能重复。")
    reference = sketches[0].frame if sketches else WorkPlaneFrame.xy()
    if (
        tolerance_frames or datum_identifiers or reference_dimensions or block_instances
    ) and reference != WorkPlaneFrame.xy():
        raise ValidationError(
            "包含独立公差、参考尺寸或块实例的 DXF 输出要求基准草图使用全局 XY 平面。"
        )
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
    if legacy_datums:
        warnings.append(
            "旧基准框及引线按画布当前字体测量；目标 CAD 字体和文字排版可能不同。"
            if legacy_datum_snapshots is not None
            else "旧基准框及引线按导出字体估算，可能与画布不同；可在画布中导出。"
        )
    if anchors:
        warnings.append("旧公差框引线锚点按当前字体计算；导出文件保存该位置，原图未修改。")
    if any(skipped.values()):
        warnings.append("旧公差框框内不可见的引线顶点未写入可见路径；原图未修改。")
    if legacy_routes or any(frame.leader_auto_route for frame in legacy_normals.values()):
        warnings.append("旧公差框自动布线仅由本软件扩展数据恢复；其他软件中仅保留可见路径。")
    if legacy_normals:
        warnings.append("旧公差框隐藏法向约束仅由本软件扩展数据恢复；其他软件中仅保留可见路径。")
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
    for frame in (*tolerance_frames, *datum_identifiers, *reference_dimensions):
        if drawing_layers is not None:
            layers[frame.layer_name.casefold()] = drawing_layers.get(frame.layer_name)
        if frame.layer_name.casefold() not in layers:
            layers[frame.layer_name.casefold()] = SketchLayer(frame.layer_name)
            if frame.layer_name != "0":
                warnings.append(f"标注图层 {frame.layer_name} 没有完整图层定义，已使用默认外观")
    for name in (
        *(instance.layer_name for instance in block_instances),
        *(
            item.layer_name
            for definition in block_definitions
            for item in (*definition.entities, *definition.texts)
        ),
    ):
        if name.casefold() not in layers:
            layers[name.casefold()] = (
                drawing_layers.get(name) if drawing_layers else SketchLayer(name)
            )
    if layers and "0" not in layers:
        layers["0"] = DEFAULT_SKETCH_LAYER
    document = _new_r2010("R2010", units=4)
    document.header["$INSUNITS"] = 4
    document.header["$MEASUREMENT"] = 1
    document.appids.new(_APPID, dxfattribs=None)
    document.appids.new(CURVE_IDENTITY_APPID, dxfattribs=None)
    document.appids.new(_DIMENSION_SNAPSHOT_APPID, dxfattribs=None)
    document.appids.new(_DIMENSION_STYLE_APPID, dxfattribs=None)
    document.appids.new(_FCF_APPID, dxfattribs=None)
    document.appids.new(_FCF_LEADER_APPID, dxfattribs=None)
    document.appids.new(_SURFACE_EXTENSION_APPID, dxfattribs=None)
    document.appids.new(_SURFACE_INDICATION_APPID, dxfattribs=None)
    document.appids.new(DATUM_APPID, dxfattribs=None)
    document.appids.new(REFERENCE_DIMENSION_APPID, dxfattribs=None)
    _write_layers(
        document, SketchLayerTable(tuple(layers.values())) if layers else SketchLayerTable()
    )
    text_style_names: dict[str, str] = {}
    if (groups or block_instances) and object_map is None:
        object_map = DxfObjectMap()
    text_handles: dict[str, str] = {}
    warnings.extend(
        write_texts_dxf(
            document, texts, text_styles, style_names=text_style_names, handle_map=text_handles
        )
    )
    if object_map is not None:
        for identity, handle in text_handles.items():
            object_map.register(DrawingObjectRef("text", identity), (handle,))
    if dimension_styles is not None and any(
        constraint.style_name is not None
        and dimension_styles.get(constraint.style_name).text_style_id is not None
        and dimension_styles.get(constraint.style_name).text_style_id not in text_style_names
        for sketch in sketches
        for constraint in sketch.constraints
    ):
        warnings.append("尺寸的文字样式引用未找到对应字体定义；导入后需重新设置字体。")
    if dimension_styles is not None and text_styles is not None:
        used_fonts = {
            dimension_styles.get(constraint.style_name).text_style_id
            for sketch in sketches
            for constraint in sketch.constraints
            if constraint.style_name is not None
        }
        for font in text_styles.styles:
            if font.style_id in used_fonts and font.font_family and not font.font_file:
                warnings.append(f"尺寸文字样式 {font.name} 未指定字体文件，其他 CAD 可能替代字体。")
    modelspace = document.modelspace()
    if tolerance_frames:
        warnings.append(
            "公差框以原生 TOLERANCE 导出；LibreCAD 2.2 实测不显示该实体，"
            "其他 CAD 的显示和编辑能力请另行核验。"
        )
        if any(frame.leader_target_mm is not None for frame in tolerance_frames):
            warnings.append(
                "原生公差框的目标 CAD 排版可能使引线与框之间出现间隙或穿入；"
                "请核对，必要时使用图形兼容导出。"
            )
    frame_dimstyles: dict[str, str] = {}
    annotation_handles: dict[tuple[str, str], list[str]] = {}
    projected_by_id = {sketch.sketch_id: sketch for sketch, _angles in projected}
    surface_owners = [
        ("datum", datum.datum_id, datum.layer_name, datum.target_mm, datum.surface_indication)
        for datum in datum_identifiers
    ] + [
        (
            "frame",
            frame.frame_id,
            frame.layer_name,
            frame.leader_target_mm,
            frame.surface_indication,
        )
        for frame in tolerance_frames
    ]
    for owner, identity, layer, target, indication in surface_owners:
        if indication is None:
            continue
        if target is None:
            raise ValidationError("表面指示缺少指向点。")
        try:
            parts = _surface_indication_dxf_parts(target, indication)
        except ValueError as exc:
            raise ValidationError(f"表面指示无法导出：{exc}") from exc
        for index, (kind, attrs) in enumerate(parts):
            component = modelspace.new_entity(kind, {**attrs, "layer": layer})
            component.set_xdata(
                _SURFACE_INDICATION_APPID, [(1000, owner), (1000, identity), (1000, str(index))]
            )
            annotation_handles.setdefault((owner, identity), []).append(component.dxf.handle)
    extension_owners = [
        ("datum", datum.datum_id, datum.layer_name, datum.attachment, datum.target_mm)
        for datum in datum_identifiers
    ] + [
        ("frame", frame.frame_id, frame.layer_name, frame.leader_attachment, frame.leader_target_mm)
        for frame in tolerance_frames
    ]
    for owner, identity, layer_name, attachment, target in extension_owners:
        if attachment is None or attachment.surface_extension is None:
            continue
        source = projected_by_id.get(attachment.sketch_id)
        entity = (
            next(
                (
                    item
                    for item in source.entities
                    if item.entity_id == attachment.reference.entity_id
                ),
                None,
            )
            if source
            else None
        )
        if entity is None:
            raise ValidationError("表面延伸目标未包含在导出中。")
        try:
            kind, attrs, expected_target = _surface_extension_dxf_geometry(attachment, entity)
        except ValueError as exc:
            raise ValidationError(f"表面延伸线无法导出：{exc}") from exc
        if target is None or math.dist(target, expected_target) > 1e-7:
            raise ValidationError("表面延伸目标位置不一致，无法导出。")
        extension = modelspace.new_entity(kind, {**attrs, "layer": layer_name})
        extension.set_xdata(_SURFACE_EXTENSION_APPID, [(1000, owner), (1000, identity)])
        annotation_handles.setdefault((owner, identity), []).append(extension.dxf.handle)
    for frame in tolerance_frames:
        if frame.leader_attachment is not None:
            source = projected_by_id.get(frame.leader_attachment.sketch_id)
            point = resolve_attachment_local(
                frame.leader_attachment,
                {entity.entity_id: entity for entity in source.entities} if source else {},
            )
            if (
                point is None
                or frame.leader_target_mm is None
                or math.dist(point, frame.leader_target_mm) > 1e-7
            ):
                warnings.append(
                    f"形位公差 {frame.frame_id[:8]} 的引线附着目标未导出或位置不一致，重新导入时将解除关联。"
                )
        if frame.leader_target_mm is not None and frame.leader_anchor_offset is None:
            raise ValidationError("公差框引线缺少框侧锚点；请在画布中导出以计算位置。")
        try:
            content = encode_rows(frame.rows)
        except ValueError as exc:
            raise ValidationError(f"形位公差框无法导出：{exc}") from exc
        if len(content.encode("utf-8")) > 255 and not _allow_long_tolerance:
            raise ValidationError(
                "形位公差框原生内容长度超过 255 字节；请拆分公差框或选择 DXF 图形兼容导出。"
            )
        angle = math.radians(frame.rotation_deg)
        dimstyle_name = _FCF_DEFAULT_DIMSTYLE
        default_font_snapshot: dict[str, object] | None = None
        explicit_font_snapshot: dict[str, object] | None = None
        if frame.text_style_id is None:
            if dimstyle_name not in document.dimstyles:
                document.dimstyles.new(
                    dimstyle_name,
                    dxfattribs={"dimtxt": 3.5, "dimscale": 1.0, "dimtxsty": "Standard"},
                )
            default_font = read_dxf_text_style(document, "Standard", 1.0)
            # ezdxf serializes an empty built-in Standard font as "txt".
            if not default_font.font_file:
                default_font = replace(default_font, font_file="txt")
            default_font_snapshot = default_font.to_mapping()
        if frame.text_style_id is not None:
            if text_styles is None or frame.text_style_id not in text_style_names:
                raise ValidationError("公差框引用的文字样式不可用，不能导出 DXF。")
            style = text_styles.get(frame.text_style_id)
            native_font = read_dxf_text_style(document, text_style_names[frame.text_style_id], 1.0)
            explicit_font_snapshot = {
                "source": style.to_mapping(),
                "native": native_font.to_mapping(),
            }
            dimstyle_name = frame_dimstyles.get(frame.text_style_id, "")
            if not dimstyle_name:
                dimstyle_name = (
                    "MYCAD_FCF_"
                    + hashlib.sha256(frame.text_style_id.encode("utf-8")).hexdigest()[:16]
                )
                document.dimstyles.new(
                    dimstyle_name,
                    dxfattribs={
                        "dimtxt": style.height_mm,
                        "dimtxsty": text_style_names[frame.text_style_id],
                    },
                )
                frame_dimstyles[frame.text_style_id] = dimstyle_name
        native = modelspace.new_entity(
            "TOLERANCE",
            {
                "layer": frame.layer_name,
                "dimstyle": dimstyle_name,
                "insert": (*frame.position_mm, 0.0),
                "x_axis_vector": (math.cos(angle), math.sin(angle), 0.0),
                "content": content,
            },
        )
        annotation_handles.setdefault(("frame", frame.frame_id), []).insert(0, native.dxf.handle)
        payload = json.dumps(
            {
                "frame": frame.to_mapping(),
                "content": content,
                **(
                    {"legacy_auto_route": legacy_routes[frame.frame_id].to_mapping()}
                    if frame.frame_id in legacy_routes
                    else {}
                ),
                **(
                    {"legacy_auto_route_bounds": bounds[frame.frame_id]}
                    if frame.frame_id in legacy_routes and frame.frame_id in bounds
                    else {}
                ),
                **(
                    {
                        "legacy_hidden_normal": legacy_normals[frame.frame_id].to_mapping(),
                        "legacy_hidden_normal_bounds": bounds[frame.frame_id],
                    }
                    if frame.frame_id in legacy_normals
                    else {}
                ),
                **({"implicit_font": default_font_snapshot} if default_font_snapshot else {}),
                **({"explicit_font": explicit_font_snapshot} if explicit_font_snapshot else {}),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        try:
            metadata_parts = pack_annotation_metadata(payload)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        compression_warning = "大型形位公差元数据已压缩；旧版 MyCAD 可能无法恢复其身份与关联。"
        if metadata_parts and metadata_parts[0] == "Z1" and compression_warning not in warnings:
            warnings.append(compression_warning)
        native.set_xdata(_FCF_APPID, [(1000, part) for part in metadata_parts])
        if frame.leader_target_mm is not None and frame.leader_anchor_offset is not None:
            legacy_arrow_warning = "旧式公差框引线箭头在原生 DXF 中使用标准闭合箭头，外观可能变化。"
            if frame.leader_arrow_style == "legacy" and legacy_arrow_warning not in warnings:
                warnings.append(legacy_arrow_warning)
            origin = frame.position_mm
            primary_target = frame.leader_target_mm
            if frame.surface_indication is not None:
                _, _, primary_target = surface_indication_geometry(
                    primary_target, frame.surface_indication
                )
            vertices = [
                primary_target,
                *((origin[0] + x, origin[1] + y) for x, y in reversed(frame.leader_offsets)),
                (
                    origin[0] + frame.leader_anchor_offset[0],
                    origin[1] + frame.leader_anchor_offset[1],
                ),
            ]
            vertices = list(_compact_frame_normal_at_anchor(frame, tuple(vertices)))
            if any(math.dist(a, b) <= 1e-9 for a, b in zip(vertices, vertices[1:], strict=False)):
                raise ValidationError("形位公差框引线相邻顶点重合，无法导出 DXF。")
            leader_style = dimstyle_name
            indication = frame.surface_indication
            segment_length = math.dist(vertices[0], vertices[1])
            configured_arrow = (indication.arrow_size_mm if indication else None) or 2.5
            if (indication is not None and indication.arrow_size_mm is not None) or (
                1e-9 < segment_length < configured_arrow
            ):
                arrow_size = min(configured_arrow, segment_length)
                style_key = f"{dimstyle_name}:{arrow_size!r}"
                leader_style = (
                    "MYCAD_FCF_ARROW_" + hashlib.sha256(style_key.encode("utf-8")).hexdigest()[:16]
                )
                if leader_style not in document.dimstyles:
                    arrow_style = document.dimstyles.duplicate_entry(dimstyle_name, leader_style)
                    arrow_style.dxf.dimasz = arrow_size
            leader = modelspace.add_leader(
                vertices,
                dimstyle=leader_style,
                dxfattribs={"layer": frame.layer_name, "annotation_handle": native.dxf.handle},
            )
            leader.set_xdata(_FCF_LEADER_APPID, [(1000, frame.frame_id)])
            annotation_handles[("frame", frame.frame_id)].append(leader.dxf.handle)
    for index, datum in enumerate(datum_identifiers):
        if datum.symbol_style == "circle":
            datum = replace(
                datum,
                bar_direction=resolve_datum_bar_direction(
                    datum, projected_by_id, {frame.frame_id: frame for frame in tolerance_frames}
                ),
            )
        datum_style = None
        datum_native_style = "Standard"
        if datum.text_style_id is not None:
            if text_styles is None or datum.text_style_id not in text_style_names:
                raise ValidationError("基准标识引用的文字样式不可用，不能导出 DXF。")
            datum_style = text_styles.get(datum.text_style_id)
            datum_native_style = text_style_names[datum.text_style_id]
            if datum_style.font_family and not datum_style.font_file:
                warnings.append(
                    f"基准文字样式 {datum_style.name} 未指定字体文件，其他 CAD 可能替代字体。"
                )
        if datum.attachment is not None:
            source = projected_by_id.get(datum.attachment.sketch_id)
            point = resolve_attachment_local(
                datum.attachment,
                {entity.entity_id: entity for entity in source.entities} if source else {},
            )
            if point is None or math.dist(point, datum.target_mm) > 1e-7:
                warnings.append(
                    f"基准 {datum.label} 的附着目标未导出或位置不一致，重新导入时将解除关联。"
                )
        try:
            compressed = write_datum(
                document,
                datum,
                index,
                style=datum_style,
                native_style=datum_native_style,
                legacy_snapshot=(legacy_datum_snapshots or {}).get(datum.datum_id),
                handle_out=annotation_handles.setdefault(("datum", datum.datum_id), []),
            )
        except ValueError as exc:
            raise ValidationError(f"基准标识无法导出：{exc}") from exc
        compression_warning = "大型基准元数据已压缩；旧版 MyCAD 可能无法恢复基准及其关联。"
        if compressed and compression_warning not in warnings:
            warnings.append(compression_warning)
    if datum_identifiers:
        warnings.append("基准标识以图形块导出；其他软件不可作为结构化基准编辑。")
        if any(datum.arrow_style != "filled" for datum in datum_identifiers):
            warnings.append("非默认基准箭头样式需要新版 MyCAD；旧版可能无法恢复结构化基准。")
        if any(datum.symbol_style == "circle" for datum in datum_identifiers):
            warnings.append("圆圈基准需要新版 MyCAD；旧版可能无法恢复结构化基准。")
    for dimension in reference_dimensions:
        try:
            handle = write_detached_dimension(document, dimension)
            if object_map is not None:
                object_map.register(
                    DrawingObjectRef("reference_dimension", dimension.dimension_id), (handle,)
                )
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"独立参考尺寸无法导出：{exc}") from exc
    if reference_dimensions:
        warnings.append("独立参考尺寸按原生 DIMENSION 导出，原文件的部分外观样式可能不同。")
    if any(
        dimension.kind in ("ordinate_x", "ordinate_y")
        and not math.isclose(math.remainder(dimension.angle_deg, 360.0), 0.0, abs_tol=1e-10)
        for dimension in reference_dimensions
    ):
        warnings.append(
            "旋转坐标轴参考尺寸依赖目标 CAD 保留轴方向；部分软件另存可能改变数值，请核对。"
        )
    exported_dimensions = 0
    for sketch, measurement_angles in projected:
        _write_sketch_entities(modelspace, sketch, warnings, object_map=object_map)
        for constraint in sketch.constraints:
            try:
                projection = measurement_angles.get(constraint.constraint_id)
                write_metadata = projection is None or constraint.projection_axis is not None
                handle = _write_dimension(
                    modelspace,
                    sketch,
                    constraint,
                    measurement_angle=None if projection is None else projection[0],
                    reflect_angle=False if projection is None else projection[1],
                    write_metadata=write_metadata,
                    drawing_style=dimension_styles.get(constraint.style_name)
                    if dimension_styles is not None and constraint.style_name is not None
                    else None,
                    text_style_names=text_style_names,
                )
                if object_map is not None:
                    object_map.register(
                        DrawingObjectRef("dimension", constraint.constraint_id, sketch.sketch_id),
                        (handle,),
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
    for entity in modelspace:
        if entity.dxftype() == "DIMENSION":
            dimension_text = entity.dxf.get("text", "")
            if isinstance(dimension_text, str) and len(dimension_text.encode("utf-8")) > 255:
                warnings.append(
                    f"尺寸文字 {entity.dxf.get('handle', '')} 超过 255 UTF-8 字节的保守兼容长度；"
                    "其他 CAD 可能截断或无法打开，请检查交换结果。"
                )
    if object_map is not None:
        for (kind, identity), handles in annotation_handles.items():
            object_map.register(
                DrawingObjectRef("tolerance" if kind == "frame" else "datum", identity),
                tuple(handles),
            )
    exported_block_instances = 0
    if block_definitions or block_instances:
        exported_block_instances = _write_drawing_blocks(
            document,
            block_definitions,
            block_instances,
            SketchLayerTable(tuple(layers.values())),
            text_styles,
            text_style_names,
            warnings,
            object_map,
        )
    if groups and object_map is not None:
        warnings.extend(write_native_groups(document, groups, object_map))
    document.saveas(path)
    if (
        not texts
        and not tolerance_frames
        and not datum_identifiers
        and not reference_dimensions
        and not any(sketch.entities for sketch in sketches)
        and not block_instances
        and not block_definitions
    ):
        warnings.append("草图中没有可导出的二维图元")
    if reference != WorkPlaneFrame.xy():
        warnings.append("工作平面位姿未写入 DXF，图元按草图局部坐标投影到 XY")
    if len(sketches) > 1:
        warnings.append("多个草图导入 MyCAD 时将合并为单张草图，原草图分组不保留")
    return DxfExchangeReport(
        "导出",
        document.dxfversion,
        "mm",
        sum(len(sketch.entities) for sketch in sketches)
        + exported_dimensions
        + len(texts)
        + len(tolerance_frames)
        + len(datum_identifiers)
        + len(reference_dimensions)
        + exported_block_instances,
        tuple(warnings),
    )


def _write_drawing_blocks(
    document: _Drawing,
    definitions: tuple[BlockDefinition, ...],
    instances: tuple[BlockInstance, ...],
    layers: SketchLayerTable,
    text_styles: TextStyleTable | None,
    style_names: dict[str, str],
    warnings: list[str],
    object_map: DxfObjectMap | None,
) -> int:
    by_id = {item.definition_id: item for item in definitions}
    if len(by_id) != len(definitions) or len({item.name.casefold() for item in definitions}) != len(
        definitions
    ):
        raise ValidationError("DXF 块定义身份或名称重复。")
    if len({item.instance_id for item in instances}) != len(instances):
        raise ValidationError("DXF 块实例身份重复。")
    if any(item.definition_id not in by_id for item in instances):
        raise ValidationError("DXF 块实例引用了不存在的定义。")
    names: dict[str, str] = {}
    used_names = {layout.name.casefold() for layout in document.blocks}
    for definition in definitions:
        name = collection_export_name(
            definition.name, definition.definition_id, used_names, "BLOCK"
        )
        used_names.add(name.casefold())
        if name != definition.name:
            warnings.append(f"块 {definition.name} 的 DXF 名称已转换为 {name}。")
        names[definition.definition_id] = name
        layout = document.blocks.new(name, base_point=(0, 0, 0))
        sketch = Sketch(
            definition.definition_id, WorkPlaneFrame.xy(), definition.entities, layers=layers
        )
        _write_sketch_entities(layout, sketch, warnings)
        warnings.extend(
            write_texts_dxf(
                document,
                definition.texts,
                text_styles,
                style_names=style_names,
                layout=layout,
                reuse_styles=True,
            )
        )
    modelspace = document.modelspace()
    exported_instances = 0
    for instance in instances:
        insert = modelspace.add_blockref(
            names[instance.definition_id],
            (*instance.insertion_mm, 0),
            dxfattribs={
                "layer": instance.layer_name,
                "rotation": instance.rotation_deg,
                "xscale": instance.scale,
                "yscale": instance.scale,
                "zscale": instance.scale,
            },
        )
        # ezdxf's attribute setter substitutes 1 for tiny nonzero scales.
        # BlockInstance already validates positivity and finiteness; preserve
        # the exact values so the native INSERT retains its geometry.
        for axis in ("xscale", "yscale", "zscale"):
            if float(cast("float", insert.dxf.get(axis))) != instance.scale:
                insert.dxf.unprotected_set(axis, instance.scale)
        if any(
            float(cast("float", insert.dxf.get(axis))) != instance.scale
            for axis in ("xscale", "yscale", "zscale")
        ):
            modelspace.delete_entity(insert)
            warnings.append(f"块实例 {instance.instance_id} 的比例无法由 DXF 保留，未导出。")
            continue
        exported_instances += 1
        if object_map is not None:
            object_map.register(
                DrawingObjectRef("block_instance", instance.instance_id), (insert.dxf.handle,)
            )
    return exported_instances


def _write_sketch_entities(
    modelspace: _Modelspace,
    sketch: Sketch,
    warnings: list[str],
    *,
    object_map: DxfObjectMap | None = None,
) -> None:
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
        elif isinstance(entity, EllipseEntity):
            ellipse = ellipse_to_dxf(entity)
            dxf_entity = modelspace.add_ellipse(
                ellipse.center,
                ellipse.major_axis,
                ellipse.ratio,
                ellipse.start_param,
                ellipse.end_param,
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
        if object_map is not None:
            object_map.register(
                DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id),
                (dxf_entity.dxf.handle,),
            )
        sweep_sign = (
            "cw"
            if isinstance(entity, ArcEntity | EllipseEntity) and entity.sweep_angle_deg < 0
            else "ccw"
        )
        dxf_entity.set_xdata(
            _APPID,
            [
                (1000, sketch.sketch_id),
                (1000, entity.entity_id),
                (1000, "rectangle" if is_rectangle else ""),
                (1000, sweep_sign),
                (1000, "1" if entity.construction else "0"),
                *(
                    ((1000, repr(entity.start_angle_deg)),)
                    if isinstance(entity, EllipseEntity)
                    else ()
                ),
                *(
                    ((1000, ""), (1000, CURVE_IDENTITY_MARKER))
                    if isinstance(entity, PolylineEntity | SplineEntity) and entity.point_ids
                    else ()
                ),
            ],
        )
        if isinstance(entity, PolylineEntity | SplineEntity) and entity.point_ids:
            try:
                parts = pack_curve_identities(entity)
                dxf_entity.set_xdata(CURVE_IDENTITY_APPID, [(1000, part) for part in parts])
            except ValueError as exc:
                warnings.append(f"曲线 {entity.entity_id[:8]} 的点身份无法导出：{exc}")


def _recover_unverified_native_dimension(
    constraint: SketchConstraint, native_dimension: _DxfEntity, scale: float
) -> tuple[SketchConstraint, tuple[str, ...]]:
    """Recover native precision and tolerance where no style snapshot can be checked."""
    warnings: list[str] = []
    native_style = cast("_NativeDimension", native_dimension).override()
    native_precision = native_style.get("dimadec" if constraint.kind == "angle" else "dimdec", 2)
    if constraint.kind == "angle" and native_precision == -1:
        native_precision = native_style.get("dimdec", 2)
    native_rounding = native_style.get("dimrnd", 0)
    unit_value = native_style.get("dimaunit", 0)
    if (
        isinstance(native_precision, int)
        and not isinstance(native_precision, bool)
        and 0 <= native_precision <= 8
        and (
            constraint.kind == "angle"
            or not isinstance(native_rounding, int | float)
            or native_rounding <= 0
            or native_rounding <= 10.0**-native_precision
        )
        and (
            constraint.kind != "angle"
            or (isinstance(unit_value, int) and unit_value in (0, 1, 2, 3))
        )
    ):
        if constraint.kind == "angle" and isinstance(unit_value, int):
            native_precision = angular_precision_in_degrees(unit_value, native_precision)
        elif constraint.unit == "mm":
            native_precision = scaled_length_precision(native_precision, scale)
        if native_precision != constraint.precision:
            constraint = replace(constraint, precision=native_precision)
            warnings.append(
                f"尺寸 {constraint.constraint_id[:8]} 的快照无法核对精度，已采用原生精度。"
            )
        if constraint.kind == "angle" and unit_value in (1, 2, 3):
            warnings.append(
                f"尺寸 {constraint.constraint_id[:8]} 的角度显示单位不保留，导入后以十进制度显示，最多 8 位小数，可能舍入。"
            )
    else:
        warnings.append(f"尺寸 {constraint.constraint_id[:8]} 的原生精度无法安全恢复。")
    if constraint.tolerance is not None:
        try:
            native_tolerance = read_native_tolerance(
                native_style, angular=constraint.kind == "angle", scale=scale
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("快照无法核对且原生公差不受支持，不能安全恢复标注") from exc
        if native_tolerance.mode == "symmetric" and constraint.tolerance.mode == "deviation":
            # Native DXF does not distinguish symmetric mode from equal signed deviations.
            native_tolerance = replace(native_tolerance, mode="deviation")
        if native_tolerance != constraint.tolerance and not (
            native_tolerance.mode == constraint.tolerance.mode == "none"
        ):
            constraint = replace(constraint, tolerance=native_tolerance)
            warnings.append(
                f"尺寸 {constraint.constraint_id[:8]} 的快照无法核对公差，已采用原生公差值。"
            )
    return constraint, tuple(warnings)


def _read_frame_text_style(
    document: _Drawing,
    entity: _DxfEntity,
    scale: float,
    text_styles: TextStyleTable | None,
    source_style_id: str | None,
    implicit_font: TextStyle | None,
    explicit_font: tuple[TextStyle, TextStyle] | None,
    metadata_valid: bool,
    frame_warnings: list[str],
) -> tuple[str | None, TextStyleTable | None]:
    """Recover a frame style without masking native edits or style conflicts."""
    imported_style_id: str | None = None
    dimstyle_name = str(entity.dxf.get("dimstyle", "Standard"))
    implicit_unchanged = False
    if implicit_font is not None and dimstyle_name.casefold() == _FCF_DEFAULT_DIMSTYLE.casefold():
        try:
            native_style = document.dimstyles.get(dimstyle_name)
            native_font_name = str(native_style.dxf.get("dimtxsty", "Standard"))
            implicit_unchanged = (
                scale == 1.0
                and native_font_name.casefold() == "standard"
                and native_style.dxf.get("dimtxt", 2.5) == 3.5
                and native_style.dxf.get("dimscale", 1.0) == 1.0
                and native_style_matches_snapshot(
                    read_dxf_text_style(document, native_font_name, 1.0), implicit_font
                )
            )
        except (DXFTableEntryError, KeyError, TypeError, ValueError):
            implicit_unchanged = False
    if not implicit_unchanged and (
        source_style_id is not None
        or implicit_font is not None
        or dimstyle_name.casefold() != "standard"
        or not metadata_valid
    ):
        try:
            native_style = document.dimstyles.get(dimstyle_name)
            font_name = str(native_style.dxf.get("dimtxsty", "Standard"))
            font = read_dxf_text_style(document, font_name, scale)
            raw_height = native_style.dxf.get("dimtxt", 2.5)
            raw_scale = native_style.dxf.get("dimscale", 1.0)
            if (
                isinstance(raw_height, bool)
                or not isinstance(raw_height, int | float)
                or isinstance(raw_scale, bool)
                or not isinstance(raw_scale, int | float)
            ):
                raise ValueError("公差框字高无效")
            height = float(raw_height) * float(raw_scale) * scale
            if not math.isfinite(height) or height <= 0:
                raise ValueError("公差框字高无效")
            if explicit_font is not None and scale == 1.0:
                saved_font, native_snapshot = explicit_font
                current_font = read_dxf_text_style(document, font_name, 1.0)
                if (
                    native_style_matches_snapshot(current_font, native_snapshot)
                    and saved_font.height_mm == height
                    and saved_font.width_factor == current_font.width_factor
                    and saved_font.font_file == current_font.font_file
                    and saved_font.font_family == current_font.font_family
                    and saved_font.font_style == current_font.font_style
                ):
                    existing_styles = () if text_styles is None else text_styles.styles
                    compatible = next(
                        (
                            item
                            for item in existing_styles
                            if replace(item, style_id=saved_font.style_id) == saved_font
                        ),
                        None,
                    )
                    collision = any(
                        item.style_id == saved_font.style_id
                        or item.name.casefold() == saved_font.name.casefold()
                        for item in existing_styles
                    )
                    if compatible is not None or not collision:
                        imported_style_id = (
                            compatible.style_id if compatible is not None else saved_font.style_id
                        )
                        if compatible is None:
                            text_styles = (
                                TextStyleTable((saved_font,), saved_font.style_id)
                                if text_styles is None
                                else replace(text_styles, styles=(*existing_styles, saved_font))
                            )
                    else:
                        frame_warnings.append("公差框文字样式名称或身份冲突，已重新分配样式。")
                else:
                    frame_warnings.append("公差框文字样式快照与原生样式不一致，已采用原生样式。")
            if imported_style_id is not None:
                return imported_style_id, text_styles
            fingerprint = hashlib.sha256(
                f"{dimstyle_name.casefold()}|{font!r}|{height!r}".encode()
            ).hexdigest()[:20]
            imported_style_id = "dxf_fcf_" + fingerprint
            existing_styles = () if text_styles is None else text_styles.styles
            if all(item.style_id != imported_style_id for item in existing_styles):
                name = f"公差 {font.name[:48]} {fingerprint[:8]}"
                if any(item.name.casefold() == name.casefold() for item in existing_styles):
                    raise ValueError("公差框文字样式名称冲突")
                imported_font = replace(
                    font, style_id=imported_style_id, name=name, height_mm=height
                )
                text_styles = (
                    TextStyleTable((imported_font,), imported_style_id)
                    if text_styles is None
                    else replace(text_styles, styles=(*existing_styles, imported_font))
                )
        except (
            DXFTableEntryError,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            imported_style_id = None
            frame_warnings.append(f"公差框文字样式无法恢复，已使用默认样式：{exc}")
    return imported_style_id, text_styles


def _preserve_datum_block_graphics(
    entity: _DxfEntity,
    scale: float,
    known_layer_names: dict[str, str],
    entities: list[SketchEntity],
    text_entities: list[object],
    warnings: list[str],
) -> None:
    """Keep supported visible primitives when datum metadata no longer matches."""

    def skipped(item: _DxfEntity, reason: str) -> None:
        warnings.append(f"基准图形块中的 {item.dxftype()} 无法保留：{reason}")

    try:
        for item in cast("_Insert", entity).virtual_entities(skipped_entity_callback=skipped):
            layer_name = str(item.dxf.layer)
            if layer_name.casefold() == "0":
                layer_name = str(entity.dxf.layer)
            layer = known_layer_names.get(layer_name.lower(), "0")
            if item.dxftype() in ("TEXT", "MTEXT"):
                item.dxf.layer = layer
                text_entities.append(item)
                continue
            try:
                if item.dxftype() == "SOLID":
                    if not _is_world_xy_normal(
                        cast("Sequence[float]", item.dxf.get("extrusion", (0, 0, 1)))
                    ):
                        raise ValueError("只支持 XY 平面的箭头")
                    points = tuple(
                        _xy(item.dxf.get(f"vtx{index}"), scale) for index in (0, 1, 3, 2)
                    )
                    for start, end in zip(points, (*points[1:], points[0]), strict=True):
                        if math.dist(start, end) > 1e-9:
                            entities.append(LineEntity(uuid4().hex, start, end, layer_name=layer))
                    warnings.append("基准箭头实心填充已转换为轮廓。")
                else:
                    parsed = _read_entity(item, uuid4().hex, "", "ccw", scale, layer, False)
                    if parsed is None:
                        warnings.append(f"基准图形块中的 {item.dxftype()} 不支持保留。")
                    else:
                        entities.append(parsed)
            except (TypeError, ValueError, OverflowError) as exc:
                warnings.append(f"基准图形块中的 {item.dxftype()} 无法保留：{exc}")
        warnings.append("基准图形块已尝试降级为普通图元和文字，不能作为基准编辑。")
    except (DXFTableEntryError, TypeError, ValueError, KeyError) as exc:
        warnings.append(f"基准图形块无法分解保留：{exc}")


def _merge_datum_fallback_texts(
    document: _Drawing,
    scale: float,
    raw_texts: list[object],
    texts: tuple[DrawingText, ...],
    styles: TextStyleTable | None,
    warnings: list[str],
) -> tuple[tuple[DrawingText, ...], TextStyleTable | None]:
    recovered, extra_styles, messages = read_texts_dxf(document, scale, entities=raw_texts)
    warnings.extend(messages)
    if extra_styles is None:
        return texts, styles
    if styles is None:
        return (*texts, *recovered), extra_styles
    remapped: dict[str, str] = {}
    for style in extra_styles.styles:
        existing = next((item for item in styles.styles if item.style_id == style.style_id), None)
        if existing is not None:
            if existing == style:
                continue
            old_id = style.style_id
            style = replace(style, style_id=uuid4().hex)
            remapped[old_id] = style.style_id
            warnings.append(f"基准降级文字样式 {style.name} 的身份冲突，已重新分配。")
        if len(styles.styles) >= 500:
            warnings.append(f"基准降级文字样式 {style.name} 超过样式数量上限，相关文字未保留。")
            continue
        names = {existing.name.casefold() for existing in styles.styles}
        if style.name.casefold() in names:
            base = f"{style.name[:40]} {style.style_id[-8:]}"
            name = base
            index = 2
            while name.casefold() in names:
                name = f"{base} {index}"
                index += 1
            style = replace(style, name=name)
        styles = replace(styles, styles=(*styles.styles, style))
    available = {style.style_id for style in styles.styles}
    converted = (
        replace(text, style_id=remapped.get(text.style_id, text.style_id)) for text in recovered
    )
    return (*texts, *(text for text in converted if text.style_id in available)), styles


def _compact_frame_normal_at_anchor(
    frame: FeatureControlFrame, vertices: tuple[Point2D, ...]
) -> tuple[Point2D, ...]:
    if (
        frame.leader_auto_normal
        and len(vertices) == 3
        and math.dist(vertices[-2], vertices[-1]) <= 1e-9
    ):
        return (vertices[0], vertices[-1])
    return vertices


def _recover_changed_frame_leader(
    supported: bool,
    actual: tuple[Point2D, ...],
    position: Point2D,
    scale: float,
) -> tuple[Point2D, tuple[Point2D, ...], Point2D] | None:
    if (
        not supported
        or not 2 <= len(actual) <= 66
        or not all(math.isfinite(value) for point in actual for value in point)
        or not all(math.dist(a, b) > 1e-9 for a, b in zip(actual, actual[1:], strict=False))
    ):
        return None
    target = (actual[0][0] * scale, actual[0][1] * scale)
    offsets = tuple(
        (point[0] * scale - position[0], point[1] * scale - position[1])
        for point in reversed(actual[1:-1])
    )
    anchor = (actual[-1][0] * scale - position[0], actual[-1][1] * scale - position[1])
    return target, offsets, anchor


def _imported_normal_is_valid(
    attachment: DatumAttachment, sketch: Sketch, target: Point2D, vertex: Point2D
) -> bool:
    normal = resolve_attachment_normal(attachment, sketch, target, enable_spline=True)
    dx, dy = vertex[0] - target[0], vertex[1] - target[1]
    length = math.hypot(dx, dy)
    return (
        normal is not None
        and length > 1e-9
        and abs((dx * normal[1] - dy * normal[0]) / length) <= 1e-7
    )


def _warn_frame_primary_arrow_change(
    leader: _Leader,
    indication: SurfaceIndication | None,
    expected: tuple[Point2D, ...],
    identity: str,
    warnings: list[str],
    scale: float,
) -> None:
    configured_arrow = (
        indication.arrow_size_mm * scale
        if indication is not None and indication.arrow_size_mm is not None
        else 2.5
    )
    expected_arrow = min(configured_arrow, math.dist(expected[0], expected[1]) * scale)
    try:
        native_style = leader.override()
        native_arrow = float(cast("float", native_style.get("dimasz", 2.5)))
        native_scale = float(cast("float", native_style.get("dimscale", 1.0)))
        same_arrow = math.isclose(native_arrow * native_scale * scale, expected_arrow, abs_tol=1e-7)
        native_block = str(native_style.get("dimldrblk", "") or "").upper()
        same_shape = native_block in ("", "_CLOSEDFILLED")
    except (DXFTableEntryError, TypeError, ValueError):
        same_arrow = False
        same_shape = False
    if not same_arrow:
        warnings.append(
            f"形位公差 {identity[:8]} 的主引线箭头尺寸已修改或不可读取，已采用本软件箭头尺寸。"
        )
    if not same_shape:
        warnings.append(
            f"形位公差 {identity[:8]} 的主引线箭头样式已修改或不可读取，已恢复默认实心箭头。"
        )


def _warn_frame_leader_graphics_change(
    leader: _Leader, frame: _DxfEntity, identity: str, warnings: list[str]
) -> None:
    layer_changed = str(leader.dxf.layer).lower() != str(frame.dxf.layer).lower()
    overrides = (
        leader.dxf.get("color", 256) != 256
        or leader.dxf.get("true_color") is not None
        or str(leader.dxf.get("linetype", "BYLAYER")).upper() != "BYLAYER"
        or leader.dxf.get("lineweight", -1) != -1
        or leader.dxf.get("transparency") is not None
        or leader.dxf.get("ltscale", 1.0) != 1.0
        or leader.dxf.get("invisible", 0) != 0
    )
    if layer_changed or overrides:
        warnings.append(
            f"形位公差 {identity[:8]} 的引线图层或独立外观无法保留，已采用公差框的图层外观。"
        )


def _preserve_unmatched_frame_leader(
    leader: _Leader,
    scale: float,
    known_layer_names: dict[str, str],
    entities: list[SketchEntity],
    warnings: list[str],
) -> None:
    try:
        if (
            not _is_world_xy_normal(
                cast("Sequence[float]", leader.dxf.get("normal_vector", (0, 0, 1)))
            )
            or int(cast("int", leader.dxf.get("path_type", 0))) != 0
            or any(abs(float(point[2])) > 1e-9 for point in leader.vertices)
        ):
            raise ValueError("只支持 XY 平面的直线引线")
        points = tuple(_xy(point, scale) for point in leader.vertices)
        if len(points) < 2:
            raise ValueError("引线顶点不足")
        layer = known_layer_names.get(str(leader.dxf.layer).lower(), "0")
        for start, end in zip(points, points[1:], strict=False):
            if math.dist(start, end) > 1e-9:
                entities.append(LineEntity(uuid4().hex, start, end, layer_name=layer))
        warnings.append(f"引线 {leader.dxf.handle} 已作为普通图元保留，关联已解除。")
        if int(cast("int", leader.dxf.get("has_arrowhead", 1))) == 0:
            return
        style = leader.override()
        block_name = str(style.get("dimldrblk", "") or "").upper()
        arrow_size = float(cast("float", style.get("dimasz", 2.5)))
        arrow_scale = float(cast("float", style.get("dimscale", 1.0)))
        size = arrow_size * arrow_scale * scale
        if block_name not in ("", "_CLOSEDFILLED") or not math.isfinite(size) or size <= 0:
            raise ValueError("箭头样式或尺寸不支持恢复")
        triangle = frame_leader_arrow(
            points[1], points[0], min(size, math.dist(points[0], points[1]))
        )
        for start, end in zip(triangle, (*triangle[1:], triangle[0]), strict=True):
            if math.dist(start, end) > 1e-9:
                entities.append(LineEntity(uuid4().hex, start, end, layer_name=layer))
        warnings.append(f"引线 {leader.dxf.handle} 的实心箭头已转换为轮廓。")
    except (DXFTableEntryError, TypeError, ValueError, KeyError, IndexError, OverflowError) as exc:
        warnings.append(f"引线 {leader.dxf.handle} 无法完整保留：{exc}")


def _validate_surface_indications(
    datum_identifiers: list[DatumIdentifier],
    tolerance_frames: list[FeatureControlFrame],
    surface_indications: dict[tuple[str, str], dict[int, list[_DxfEntity]]],
    scale: float,
    warnings: list[str],
) -> set[tuple[str, str]]:
    indication_owner_counts: dict[tuple[str, str], int] = {}
    for owner, identity in [
        *(("datum", item.datum_id) for item in datum_identifiers),
        *(("frame", item.frame_id) for item in tolerance_frames),
    ]:
        key = (owner, identity)
        indication_owner_counts[key] = indication_owner_counts.get(key, 0) + 1
    verified_indications: set[tuple[str, str]] = set()

    def indication_valid(
        owner: str, identity: str, target: Point2D, indication: SurfaceIndication
    ) -> bool:
        key = (owner, identity)
        components = surface_indications.get(key, {})
        if indication_owner_counts.get(key) != 1:
            return False
        try:
            parts = _surface_indication_dxf_parts(target, indication, arrow_size=2.5 * scale)
        except ValueError:
            return False
        if set(components) != set(range(len(parts))):
            return False
        for index, (kind, expected) in enumerate(parts):
            matches = components[index]
            if len(matches) != 1 or not _surface_indication_component_matches(
                matches[0], kind, expected, scale
            ):
                return False
        verified_indications.add(key)
        return True

    for index, datum in enumerate(datum_identifiers):
        indication = datum.surface_indication
        if indication is not None and not indication_valid(
            "datum", datum.datum_id, datum.target_mm, indication
        ):
            _, _, landing = surface_indication_geometry(datum.target_mm, indication)
            datum_identifiers[index] = replace(
                datum,
                target_mm=landing,
                surface_indication=None,
                attachment=None,
                annotation_attachment=None,
                leader_auto_normal=False,
                leader_auto_route=False,
                route_avoid_crossing=False,
                route_track_target=False,
                route_algorithm_version=1,
            )
            warnings.append(f"基准 {datum.label} 的表面指示图形缺失或已修改，已解除关联。")
    for index, frame in enumerate(tolerance_frames):
        indication = frame.surface_indication
        if (
            indication is not None
            and frame.leader_target_mm is not None
            and not indication_valid("frame", frame.frame_id, frame.leader_target_mm, indication)
        ):
            _, _, landing = surface_indication_geometry(frame.leader_target_mm, indication)
            tolerance_frames[index] = replace(
                frame,
                leader_target_mm=landing,
                surface_indication=None,
                leader_attachment=None,
                leader_annotation_attachment=None,
            )
            warnings.append(
                f"形位公差 {frame.frame_id[:8]} 的表面指示图形缺失或已修改，已解除关联。"
            )

    return verified_indications


def _preserve_unverified_surface_indications(
    surface_indications: dict[tuple[str, str], dict[int, list[_DxfEntity]]],
    verified_indications: set[tuple[str, str]],
    known_layer_names: dict[str, str],
    scale: float,
    entities: list[SketchEntity],
    warnings: list[str],
) -> None:
    for key in surface_indications.keys() - verified_indications:
        for matches in surface_indications[key].values():
            for entity in matches:
                layer = known_layer_names.get(str(entity.dxf.layer).lower(), "0")
                try:
                    if entity.dxftype() == "SOLID":
                        points = tuple(
                            _xy(entity.dxf.get(f"vtx{index}"), scale) for index in range(3)
                        )
                        for start, end in zip(points, (*points[1:], points[0]), strict=True):
                            if math.dist(start, end) > 1e-9:
                                entities.append(
                                    LineEntity(uuid4().hex, start, end, layer_name=layer)
                                )
                    else:
                        parsed = _read_entity(
                            entity, uuid4().hex, "", "ccw", scale, layer, False, ""
                        )
                        if parsed is not None:
                            entities.append(parsed)
                        else:
                            warnings.append("失关联的表面指示图形类型不受支持，无法保留。")
                except (TypeError, ValueError, OverflowError) as exc:
                    warnings.append(f"表面指示图形无法保留：{exc}")
        warnings.append("失关联的表面指示图形已尝试作为普通图元保留。")


def _frame_metadata_identity_counts(entities: Iterable[_DxfEntity]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in entities:
        if entity.dxftype() != "TOLERANCE":
            continue
        values = _xdata_values(entity, _FCF_APPID)
        if not values:
            continue
        try:
            payload: object = json.loads(unpack_annotation_metadata(values))
            if not isinstance(payload, Mapping):
                continue
            frame = cast("Mapping[str, object]", payload).get("frame")
            if not isinstance(frame, Mapping):
                continue
            identity = cast("Mapping[str, object]", frame).get("frame_id")
            if isinstance(identity, str) and _is_identity(identity):
                counts[identity] = counts.get(identity, 0) + 1
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return counts


def _read_native_frame_leader(
    candidates: list[_Leader],
    position: Point2D,
    scale: float,
    entity: _DxfEntity,
    identity: str,
    warnings: list[str],
) -> tuple[Point2D, tuple[Point2D, ...], Point2D] | None:
    if len(candidates) != 1:
        return None
    leader = candidates[0]
    if _xdata_values(leader, _FCF_LEADER_APPID):
        return None
    supported = (
        leader.dxf.get("path_type", 0) == 0
        and leader.dxf.get("has_arrowhead", 1) == 1
        and all(abs(float(point[2])) <= 1e-9 for point in leader.vertices)
        and math.dist(
            cast("Sequence[float]", leader.dxf.get("normal_vector", (0, 0, 1))), (0, 0, 1)
        )
        <= 1e-9
    )
    actual = tuple((float(point[0]), float(point[1])) for point in leader.vertices)
    result = _recover_changed_frame_leader(supported, actual, position, scale)
    if result is not None:
        _warn_frame_primary_arrow_change(leader, None, actual, identity, warnings, scale)
        _warn_frame_leader_graphics_change(leader, entity, identity, warnings)
        warnings.append(f"形位公差 {identity[:8]} 的引线已按原生关联导入，几何附着未恢复。")
    return result


def _retain_auto_route(
    source: FeatureControlFrame | None,
    metadata_valid: bool,
    normal: bool,
    offsets: tuple[Point2D, ...],
    scale: float,
) -> bool:
    if not metadata_valid or source is None or not source.leader_auto_route or not normal:
        return False
    if len(source.leader_offsets) != len(offsets):
        return False
    return all(
        math.dist((old[0] * scale, old[1] * scale), new) <= 1e-8
        for old, new in zip(source.leader_offsets, offsets, strict=True)
    )


def _retain_route_crossing_policy(
    source: FeatureControlFrame | None,
    metadata_valid: bool,
    normal: bool,
    offsets: tuple[Point2D, ...],
    scale: float,
) -> bool:
    return bool(
        source is not None
        and source.route_avoid_crossing
        and _retain_auto_route(source, metadata_valid, normal, offsets, scale)
    )


def _retain_route_target_tracking(
    source: FeatureControlFrame | None,
    metadata_valid: bool,
    normal: bool,
    offsets: tuple[Point2D, ...],
    scale: float,
) -> bool:
    return bool(
        source is not None
        and source.route_track_target
        and _retain_route_crossing_policy(source, metadata_valid, normal, offsets, scale)
    )


def _retain_route_algorithm_version(
    source: FeatureControlFrame | None,
    metadata_valid: bool,
    normal: bool,
    offsets: tuple[Point2D, ...],
    scale: float,
) -> int:
    if source is not None and _retain_route_target_tracking(
        source, metadata_valid, normal, offsets, scale
    ):
        return source.route_algorithm_version
    return 1


def _read_frame_arrow_style(source: FeatureControlFrame | None, metadata_valid: bool) -> str:
    if metadata_valid and source is not None:
        return source.leader_arrow_style
    return "closed_filled"


def _restore_legacy_auto_route(
    metadata: tuple[str, ...],
    source: FeatureControlFrame | None,
    candidate: FeatureControlFrame,
    warnings: list[str],
    scale: float,
    unique_identity: bool,
) -> FeatureControlFrame:
    """Restore hidden routing vertices only when native geometry is unchanged."""
    if not metadata:
        return candidate
    has_legacy_route = False
    hidden_normal = False
    try:
        raw: object = json.loads(unpack_annotation_metadata(metadata))
        if not isinstance(raw, Mapping):
            return candidate
        payload = cast("Mapping[str, object]", raw)
        hidden_normal = "legacy_hidden_normal" in payload
        if not hidden_normal and "legacy_auto_route" not in payload:
            return candidate
        has_legacy_route = True
        if hidden_normal and "legacy_auto_route" in payload:
            raise ValueError("旧引线约束元数据冲突")
        value = payload["legacy_hidden_normal" if hidden_normal else "legacy_auto_route"]
        original = FeatureControlFrame.from_mapping(value)
        unsafe_warnings = any(
            not warning.endswith("的引线原生关联缺失，已依据唯一身份恢复。") for warning in warnings
        )
        if (
            source is None
            or not unique_identity
            or scale != 1
            or unsafe_warnings
            or candidate != source
        ):
            raise ValueError("原生公差框或引线已变化")
        count = len(original.leader_offsets) - len(source.leader_offsets)
        height = 3.5
        if original.text_style_id is not None:
            explicit_font = payload.get("explicit_font")
            if not isinstance(explicit_font, Mapping):
                raise ValueError("缺少文字样式快照")
            saved_font = TextStyle.from_mapping(
                cast("Mapping[str, object]", explicit_font).get("source")
            )
            if saved_font.style_id != original.text_style_id:
                raise ValueError("文字样式身份不一致")
            height = saved_font.height_mm
        bounds_key = "legacy_hidden_normal_bounds" if hidden_normal else "legacy_auto_route_bounds"
        layout_matches = (
            _legacy_frame_layout_matches(
                original,
                payload[bounds_key],
                source.leader_anchor_offset or (0.0, 0.0),
                count,
                height,
            )
            if bounds_key in payload
            else not hidden_normal and _legacy_hidden_vertices_in_symbol(original, count, height)
        )
        if (
            not original.leader_auto_normal
            or (not hidden_normal and not original.leader_auto_route)
            or original.leader_anchor_offset is not None
            or not 0 < count <= len(original.leader_offsets)
            or hidden_normal != (count == len(original.leader_offsets))
            or original.leader_offsets[count:] != source.leader_offsets
            or source.leader_anchor_offset is None
            or not layout_matches
            or replace(
                original,
                leader_anchor_offset=source.leader_anchor_offset,
                leader_offsets=source.leader_offsets,
                leader_auto_normal=False if hidden_normal else original.leader_auto_normal,
                leader_auto_route=False,
                route_avoid_crossing=False,
                route_track_target=False,
                route_algorithm_version=1,
            )
            != source
        ):
            raise ValueError("旧自动布线元数据不一致")
        return original
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        if has_legacy_route:
            warnings.append(
                f"形位公差 {candidate.frame_id[:8]} 的旧引线约束无法核验，已保留可见引线并解除相关约束。"
                if hidden_normal
                else f"形位公差 {candidate.frame_id[:8]} 的旧自动布线无法核验，已保留可见引线并解除自动布线。"
            )
        return candidate


def _read_frame_leader(
    metadata_valid: bool,
    source_frame: FeatureControlFrame | None,
    frame_leaders: dict[str, list[_Leader]],
    frame_identity_counts: dict[str, int],
    handled_frame_leaders: set[str],
    position: Point2D,
    scale: float,
    rotation: float,
    entity: _DxfEntity,
    identity: str,
    frame_warnings: list[str],
) -> tuple[
    Point2D | None,
    tuple[Point2D, ...],
    Point2D | None,
    DatumAttachment | None,
    AnnotationAttachment | None,
    SurfaceIndication | None,
    bool,
]:
    leader_target: tuple[float, float] | None = None
    leader_offsets: tuple[tuple[float, float], ...] = ()
    leader_anchor: tuple[float, float] | None = None
    leader_attachment: DatumAttachment | None = None
    leader_annotation_attachment: AnnotationAttachment | None = None
    surface_indication: SurfaceIndication | None = None
    leader_auto_normal = False
    if metadata_valid and source_frame is not None and source_frame.leader_target_mm is not None:
        candidates = frame_leaders.get(source_frame.frame_id, [])
        source_anchor = source_frame.leader_anchor_offset
        if len(candidates) == 1 and source_anchor is not None:
            leader = candidates[0]
            shift = (
                position[0] / scale - source_frame.position_mm[0],
                position[1] / scale - source_frame.position_mm[1],
            )
            origin = (
                source_frame.position_mm[0] + shift[0],
                source_frame.position_mm[1] + shift[1],
            )
            target = (
                source_frame.leader_target_mm[0] + shift[0],
                source_frame.leader_target_mm[1] + shift[1],
            )
            primary_target = target
            if source_frame.surface_indication is not None:
                _, _, primary_target = surface_indication_geometry(
                    target, source_frame.surface_indication
                )
            expected = (
                primary_target,
                *((origin[0] + x, origin[1] + y) for x, y in reversed(source_frame.leader_offsets)),
                (origin[0] + source_anchor[0], origin[1] + source_anchor[1]),
            )
            actual = tuple((float(point[0]), float(point[1])) for point in leader.vertices)
            compact_expected = _compact_frame_normal_at_anchor(source_frame, expected)
            if len(actual) == len(compact_expected):
                expected = compact_expected
            annotation_handle = str(leader.dxf.get("annotation_handle", "") or "")
            missing_native_link = annotation_handle in ("", "0")
            supported_leader = (
                (
                    annotation_handle == str(entity.dxf.handle)
                    or (
                        missing_native_link
                        and frame_identity_counts.get(source_frame.frame_id) == 1
                    )
                )
                and leader.dxf.get("path_type", 0) == 0
                and leader.dxf.get("has_arrowhead", 1) == 1
                and all(abs(float(point[2])) <= 1e-9 for point in leader.vertices)
                and math.dist(
                    cast("Sequence[float]", leader.dxf.get("normal_vector", (0, 0, 1))),
                    (0, 0, 1),
                )
                <= 1e-9
            )
            if (
                supported_leader
                and len(actual) == len(expected)
                and all(math.dist(a, b) <= 1e-7 for a, b in zip(actual, expected, strict=True))
                and math.isclose(
                    math.remainder(rotation - source_frame.rotation_deg, 360),
                    0,
                    abs_tol=1e-7,
                )
            ):
                handled_frame_leaders.add(str(leader.dxf.handle))
                _warn_frame_primary_arrow_change(
                    leader,
                    source_frame.surface_indication,
                    expected,
                    identity,
                    frame_warnings,
                    scale,
                )
                leader_target = (target[0] * scale, target[1] * scale)
                leader_offsets = tuple(
                    (x * scale, y * scale) for x, y in source_frame.leader_offsets
                )
                leader_anchor = (source_anchor[0] * scale, source_anchor[1] * scale)
                leader_attachment = source_frame.leader_attachment
                leader_annotation_attachment = source_frame.leader_annotation_attachment
                leader_auto_normal = source_frame.leader_auto_normal
                if source_frame.surface_indication is not None:
                    surface_indication = _scaled_surface_indication(
                        source_frame.surface_indication, scale
                    )
            elif (
                recovered := _recover_changed_frame_leader(
                    supported_leader
                    and (
                        source_frame.surface_indication is None
                        or (bool(actual) and math.dist(actual[0], primary_target) <= 1e-7)
                    ),
                    actual,
                    position,
                    scale,
                )
            ) is not None:
                handled_frame_leaders.add(str(leader.dxf.handle))
                leader_target, leader_offsets, leader_anchor = recovered
                _warn_frame_primary_arrow_change(
                    leader, source_frame.surface_indication, actual, identity, frame_warnings, scale
                )
                if source_frame.surface_indication is not None:
                    leader_target = (target[0] * scale, target[1] * scale)
                    leader_attachment = source_frame.leader_attachment
                    leader_annotation_attachment = source_frame.leader_annotation_attachment
                    surface_indication = _scaled_surface_indication(
                        source_frame.surface_indication, scale
                    )
                    frame_warnings.append(
                        f"形位公差 {identity[:8]} 的主引线已在外部修改，已按原生顶点恢复。"
                    )
                elif math.dist(actual[0], target) <= 1e-7:
                    leader_attachment = source_frame.leader_attachment
                    leader_annotation_attachment = source_frame.leader_annotation_attachment
                    leader_auto_normal = (
                        source_frame.leader_auto_normal
                        and len(actual) > 2
                        and len(expected) > 2
                        and math.dist(actual[1], expected[1]) <= 1e-7
                    )
                    constraint_notice = (
                        "法向约束已解除。"
                        if source_frame.leader_auto_normal and not leader_auto_normal
                        else "目标关联将另行核验。"
                    )
                    frame_warnings.append(
                        f"形位公差 {identity[:8]} 的引线已在外部修改，"
                        f"已按原生顶点恢复；{constraint_notice}"
                    )
                else:
                    frame_warnings.append(
                        f"形位公差 {identity[:8]} 的引线已在外部修改，"
                        "已按原生顶点恢复并解除原有附着及法向约束。"
                    )
            if leader_target is not None:
                if missing_native_link:
                    frame_warnings.append(
                        f"形位公差 {identity[:8]} 的引线原生关联缺失，已依据唯一身份恢复。"
                    )
                _warn_frame_leader_graphics_change(leader, entity, identity, frame_warnings)
        if leader_target is None:
            frame_warnings.append(f"形位公差 {identity[:8]} 的引线缺失或已修改，未恢复引线。")
    return (
        leader_target,
        leader_offsets,
        leader_anchor,
        leader_attachment,
        leader_annotation_attachment,
        surface_indication,
        leader_auto_normal,
    )


def _restore_imported_curve_ids(
    entity: _DxfEntity,
    parsed: SketchEntity,
    values: tuple[str, ...],
    scale: float,
    entities: list[SketchEntity],
    warnings: list[str],
    unverified: set[tuple[str, str]],
    owners: dict[str, tuple[int, tuple[str, str] | None]],
) -> SketchEntity:
    parts = _xdata_values(entity, CURVE_IDENTITY_APPID)
    marker = len(values) >= 7 and values[6] == CURVE_IDENTITY_MARKER
    if marker or parts:
        try:
            if not isinstance(parsed, PolylineEntity | SplineEntity) or not parts:
                raise ValueError("点身份元数据缺失或图元类型已改变。")
            parsed = restore_curve_identities(parsed, parts, scale)
        except ValueError as exc:
            warnings.append(f"曲线 {entity.dxf.handle} 的点身份无法恢复：{exc}")
            if len(values) >= 2:
                unverified.add((values[0], values[1]))
    if isinstance(parsed, PolylineEntity | SplineEntity) and parsed.point_ids:
        collisions = {owners[point_id] for point_id in parsed.point_ids if point_id in owners}
        source_key = (values[0], values[1]) if len(values) >= 2 else None
        if collisions:
            warnings.append(f"曲线 {entity.dxf.handle} 的点身份重复，相关身份及附着已解除。")
            if source_key is not None:
                unverified.add(source_key)
            for index, previous_key in collisions:
                prior = entities[index]
                if isinstance(prior, PolylineEntity | SplineEntity):
                    entities[index] = replace(prior, point_ids=())
                if previous_key is not None:
                    unverified.add(previous_key)
            parsed = replace(parsed, point_ids=())
        else:
            kind = "polyline" if isinstance(parsed, PolylineEntity) else "spline"
            expected = new_curve_point_identities(parsed.entity_id, kind, len(parsed.point_ids))
            if set(parsed.point_ids) != set(expected):
                warnings.append(f"曲线 {entity.dxf.handle} 的点身份不属于该图元，附着已解除。")
                if source_key is not None:
                    unverified.add(source_key)
                parsed = replace(parsed, point_ids=())
            else:
                for point_id in parsed.point_ids:
                    owners[point_id] = (len(entities), source_key)
    return parsed


def _reconcile_datum_text_style(
    document: _Drawing,
    entity: _DxfEntity,
    scale: float,
    datum: DatumIdentifier,
    text_styles: TextStyleTable | None,
    warnings: list[str],
) -> tuple[DatumIdentifier, TextStyleTable | None]:
    if datum.text_style_id is None:
        values = _xdata_values(entity, DATUM_APPID)
        initial_metadata: object = json.loads(unpack_annotation_metadata(values))
        if (
            not isinstance(initial_metadata, Mapping)
            or "text_style_snapshot" not in initial_metadata
        ):
            return datum, text_styles
    font = read_datum_text_style(document, entity, scale)
    existing = () if text_styles is None else text_styles.styles
    snapshot_conflict = False
    values = _xdata_values(entity, DATUM_APPID)
    try:
        raw: object = json.loads(unpack_annotation_metadata(values))
        if not isinstance(raw, Mapping):
            raise ValueError("基准元数据无效")
        metadata = cast("Mapping[str, object]", raw)
        if "text_style_snapshot" in metadata:
            snapshot = metadata["text_style_snapshot"]
            if not isinstance(snapshot, Mapping):
                raise ValueError("基准文字样式快照无效")
            snapshot_data = cast("Mapping[str, object]", snapshot)
            if set(snapshot_data) != {"source", "native"}:
                raise ValueError("基准文字样式快照字段无效")
            source = TextStyle.from_mapping(snapshot_data["source"])
            native = TextStyle.from_mapping(snapshot_data["native"])
            current = read_datum_text_style(document, entity, 1.0)
            if (
                source.style_id == datum.text_style_id
                and native_style_matches_snapshot(current, native)
                and replace(native, style_id=source.style_id, name=source.name) == source
            ):
                scaled = replace(source, height_mm=source.height_mm * scale)
                compatible = next((item for item in existing if item == scaled), None)
                collision = any(
                    item.style_id == scaled.style_id
                    or item.name.casefold() == scaled.name.casefold()
                    for item in existing
                )
                if compatible is not None:
                    return datum, text_styles
                if not collision:
                    text_styles = (
                        TextStyleTable((scaled,), scaled.style_id)
                        if text_styles is None
                        else replace(text_styles, styles=(*existing, scaled))
                    )
                    return datum, text_styles
                snapshot_conflict = True
                warnings.append(
                    f"基准 {datum.label} 的文字样式名称或身份冲突，已使用独立导入样式。"
                )
            else:
                warnings.append(
                    f"基准 {datum.label} 的文字样式快照与原生字体不一致，已采用原生字体。"
                )
    except (DXFTableEntryError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        warnings.append(f"基准 {datum.label} 的文字样式快照无效，已采用原生字体。")
    original = next((item for item in existing if item.style_id == datum.text_style_id), None)
    if (
        original is not None
        and not snapshot_conflict
        and replace(font, style_id=original.style_id, name=original.name) == original
    ):
        return datum, text_styles
    fingerprint = hashlib.sha256(repr(font).encode()).hexdigest()[:20]
    for index in range(2 * len(existing) + 1):
        suffix = "" if index == 0 else f"_{index}"
        style_id = "dxf_datum_" + fingerprint + suffix
        name = f"基准 {font.name[:48]} {fingerprint[:8]}{suffix}"
        same_id = next((item for item in existing if item.style_id == style_id), None)
        if same_id is not None:
            if replace(font, style_id=same_id.style_id, name=same_id.name) == same_id:
                break
            continue
        if any(item.name.casefold() == name.casefold() for item in existing):
            continue
        imported_font = replace(font, style_id=style_id, name=name)
        text_styles = (
            TextStyleTable((imported_font,), style_id)
            if text_styles is None
            else replace(text_styles, styles=(*existing, imported_font))
        )
        break
    else:
        raise ValueError("无法为基准生成唯一文字样式")
    if (
        original is not None
        and replace(font, style_id=original.style_id, name=original.name) != original
    ):
        warnings.append(f"基准 {datum.label} 的原生字体与同身份文字样式不同，已使用独立导入样式。")
    return replace(datum, text_style_id=style_id), text_styles


def _finalize_datum_imports(
    document: _Drawing,
    pending: list[tuple[DatumIdentifier, _DxfEntity]],
    scale: float,
    text_styles: TextStyleTable | None,
    known_layer_names: dict[str, str],
    entities: list[SketchEntity],
    fallback_text_entities: list[object],
    warnings: list[str],
) -> tuple[list[DatumIdentifier], TextStyleTable | None]:
    """Resolve datum styles after all frame and ordinary text styles are known."""
    datums: list[DatumIdentifier] = []
    for datum, entity in pending:
        try:
            datum, text_styles = _reconcile_datum_text_style(
                document, entity, scale, datum, text_styles, warnings
            )
            datums.append(datum)
        except (DXFTableEntryError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            warnings.append(f"基准图形块 {entity.dxf.handle} 无法导入：{exc}")
            _preserve_datum_block_graphics(
                entity, scale, known_layer_names, entities, fallback_text_entities, warnings
            )
    return datums, text_styles


def _block_has_unrepresentable_appearance(entity: _DxfEntity, *, member: bool) -> bool:
    """Block members retain layers, but not individual DXF display overrides."""
    attributes = entity.dxf
    zero_layer_member = member and str(attributes.get("layer", "0")).casefold() == "0"
    color = attributes.get("color", 256)
    lineweight = attributes.get("lineweight", -1)
    linetype = str(attributes.get("linetype", "BYLAYER")).upper()
    return (
        color != 256
        and not (zero_layer_member and color == 0)
        or attributes.get("true_color") is not None
        or attributes.get("color_name") is not None
        or linetype != "BYLAYER"
        and not (zero_layer_member and linetype == "BYBLOCK")
        or lineweight != -1
        and not (zero_layer_member and lineweight == -2)
        or attributes.get("ltscale", 1.0) != 1.0
        or attributes.get("transparency") is not None
    )


def _block_plane_height(
    layout: _BlockLayout, members: tuple[_DxfEntity, ...]
) -> tuple[float, float]:
    """Find a single member plane and the definition base in native DXF units."""
    _x, _y, base_z = _xyz(layout.block.dxf.get("base_point", (0, 0, 0)))
    plane_z: float | None = None
    for member in members:
        kind = member.dxftype()
        points: tuple[object, ...] = ()
        if kind == "POINT":
            points = (member.dxf.location,)
        elif kind == "LINE":
            points = (member.dxf.start, member.dxf.end)
        elif kind in {"CIRCLE", "ARC", "ELLIPSE"}:
            points = (member.dxf.center,)
        elif kind == "LWPOLYLINE":
            elevation = member.dxf.elevation
            raw_z: object = getattr(elevation, "z", elevation)
            if (
                isinstance(raw_z, bool)
                or not isinstance(raw_z, int | float)
                or not math.isfinite(raw_z)
            ):
                raise ValueError("块成员高度无效")
            points = ((0.0, 0.0, float(raw_z)),)
        elif kind == "POLYLINE":
            points = (member.dxf.get("elevation", (0, 0, 0)),)
        elif kind == "SPLINE":
            points = tuple(cast("_Spline", member).control_points)
        elif kind == "TEXT":
            aligned = bool(member.dxf.get("halign", 0) or member.dxf.get("valign", 0))
            points = (member.dxf.get("align_point" if aligned else "insert", (0, 0, 0)),)
        elif kind == "MTEXT":
            points = (member.dxf.get("insert", (0, 0, 0)),)
        for point in points:
            z = _xyz(point)[2]
            if plane_z is None:
                plane_z = z
            elif z != plane_z:
                raise ValueError("块成员不在同一 XY 平面")
    return base_z, base_z if plane_z is None else plane_z


def _read_drawing_blocks(
    document: _Drawing,
    raw_inserts: tuple[_DxfEntity, ...],
    scale: float,
    layers: SketchLayerTable,
    layer_names: dict[str, str],
    styles: TextStyleTable | None,
    *,
    include_nested_referenced: bool = False,
) -> tuple[
    tuple[BlockDefinition, ...],
    tuple[BlockInstance, ...],
    dict[str, str],
    TextStyleTable | None,
    tuple[str, ...],
]:
    """Preflight each native block completely before admitting any instance."""
    definitions: dict[str, BlockDefinition] = {}
    rejected: dict[str, str] = {}
    instances: list[BlockInstance] = []
    handles: dict[str, str] = {}
    warnings: list[str] = []
    used_definition_names: set[str] = set()
    plane_cache: dict[str, tuple[float, float]] = {}

    def plane_height(name: str, layout: _BlockLayout) -> tuple[float, float]:
        key = name.lower()
        if key not in plane_cache:
            plane_cache[key] = _block_plane_height(layout, tuple(layout))
        return plane_cache[key]

    def read_definition(name: str) -> BlockDefinition:
        nonlocal styles
        key = name.lower()

        try:
            layout = document.blocks.get(name)
            if layout is None:
                raise ValueError("块定义不存在")
            if (
                layout.block_record.has_extension_dict
                and "ACAD_ENHANCEDBLOCK" in layout.block_record.get_extension_dict()
            ):
                raise ValueError("动态块不在支持范围")
            flags = int(cast("int", layout.block.dxf.get("flags", 0)))
            if flags & (1 | 2 | 4 | 8 | 16 | 32 | 64):
                raise ValueError("不支持匿名、含属性或外部依赖块定义")
            base_x, base_y, _base_z = _xyz(layout.block.dxf.get("base_point", (0, 0, 0)))
            base = (base_x * scale, base_y * scale)
            raw_entities = tuple(layout)
            _base_z, plane_z = plane_height(name, layout)
            for item in raw_entities:
                if item.dxftype() in {
                    "LWPOLYLINE",
                    "POLYLINE",
                    "CIRCLE",
                    "ARC",
                    "ELLIPSE",
                    "TEXT",
                    "MTEXT",
                } and not _is_exact_xy_normal(item.dxf.get("extrusion", (0, 0, 1))):
                    raise ValueError(f"块成员 {item.dxftype()} 不在正向 XY 平面")
                member_layer = str(item.dxf.get("layer", "0"))
                if (
                    member_layer.casefold() != "0"
                    and document.layers.get(member_layer).transparency > 0
                ):
                    raise ValueError(f"块成员图层 {member_layer} 的透明度无法保留")
                if _block_has_unrepresentable_appearance(item, member=True):
                    raise ValueError(f"包含无法保留逐对象外观的 {item.dxftype()} 成员")
                if item.dxf.get("invisible", 0):
                    raise ValueError(f"包含隐藏的 {item.dxftype()} 成员，无法保留其可见性")
                if item.dxf.hasattr("thickness") and item.dxf.get("thickness", 0):
                    raise ValueError(f"包含具有三维厚度的 {item.dxftype()} 成员")
                if item.dxftype() == "MTEXT" and (
                    item.dxf.get("bg_fill", 0) or item.dxf.get("flow_direction", 5) == 3
                ):
                    raise ValueError("包含不支持背景填充或竖排的文字")
            text_entities = tuple(
                item for item in raw_entities if item.dxftype() in {"TEXT", "MTEXT"}
            )
            geometry: list[SketchEntity] = []
            for item in raw_entities:
                if item.dxftype() in {"TEXT", "MTEXT"}:
                    continue
                layer_name = layers.get(layer_names[str(item.dxf.get("layer", "0")).lower()]).name
                values = _xdata_values(item)
                parsed = _read_entity(
                    item,
                    uuid4().hex,
                    values[2] if len(values) > 2 else "",
                    values[3] if len(values) > 3 else "ccw",
                    scale,
                    layer_name,
                    False,
                    values[5] if len(values) > 5 else "",
                    strict_block=True,
                    block_plane_z=plane_z,
                )
                if parsed is None:
                    raise ValueError(f"包含不支持的 {item.dxftype()} 成员")
                geometry.append(parsed)
            try:
                imported_texts, source_styles, messages = read_texts_dxf(
                    document,
                    scale,
                    entities=text_entities,
                    strict_format=True,
                    plane_z=plane_z,
                )
                imported_texts = tuple(
                    replace(item, layer_name=layer_names[item.layer_name.lower()])
                    for item in imported_texts
                )
            except ValueError as exc:
                raise ValueError(f"块内文字不受支持：{exc}") from exc
            if len(imported_texts) != len(text_entities):
                raise ValueError("块内文字不受支持")
            candidate_styles = styles
            if source_styles is not None:
                if candidate_styles is None:
                    candidate_styles = source_styles
                else:
                    original_texts = imported_texts
                    existing_names = {item.name.casefold() for item in candidate_styles.styles}
                    candidate_styles, imported_texts = reconcile_text_styles(
                        imported_texts, source_styles, candidate_styles
                    )
                    renamed = {
                        (
                            source_styles.get(original.style_id).name,
                            candidate_styles.get(clone.style_id).name,
                        )
                        for original, clone in zip(original_texts, imported_texts, strict=True)
                    }
                    messages += tuple(
                        f"文字样式名称冲突：{old} → {new}。"
                        for old, new in sorted(renamed)
                        if old != new and old.casefold() in existing_names
                    )
            delta = (-base[0], -base[1])
            geometry_tuple = tuple(geometry)
            if geometry_tuple:
                geometry_tuple = move_entities(
                    geometry_tuple,
                    tuple(item.entity_id for item in geometry_tuple),
                    delta,
                    preserve_rectangle_order=True,
                )
            imported_name = unique_import_name(name, used_definition_names)
            definition = BlockDefinition(
                uuid4().hex,
                imported_name,
                geometry_tuple,
                tuple(move_text(item, delta) for item in imported_texts),
            )
            definitions[key] = definition
            used_definition_names.add(imported_name.casefold())
            if imported_name != name:
                warnings.append(f"块名称冲突：{name} → {imported_name}。")
            styles = candidate_styles
            warnings.extend(messages)
            return definition
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            rejected[key] = str(exc)
            raise

    for raw in raw_inserts:
        name = str(raw.dxf.get("name", ""))
        try:
            insert = cast("_Insert", raw)
            if not name or name.startswith("*"):
                raise ValueError("匿名或无名块不作为普通用户块导入")
            if raw.dxf.get("invisible", 0):
                raise ValueError("隐藏块实例无法保留其可见性")
            if _block_has_unrepresentable_appearance(raw, member=False):
                raise ValueError("块实例的逐对象外观无法保留")
            clipping = XClip(cast("Insert", raw))
            if clipping.has_clipping_path and clipping.is_clipping_enabled:
                raise ValueError("块实例启用了裁剪，无法保留裁剪后的外观")
            if (
                insert.attribs
                or int(cast("int", raw.dxf.get("row_count", 1))) != 1
                or int(cast("int", raw.dxf.get("column_count", 1))) != 1
            ):
                raise ValueError("不支持块属性或多重插入")
            if not _is_exact_xy_normal(
                cast("Sequence[float]", raw.dxf.get("extrusion", (0, 0, 1)))
            ):
                raise ValueError("块实例不在正向 XY 平面")
            xscale = float(cast("float", raw.dxf.get("xscale", 1)))
            yscale = float(cast("float", raw.dxf.get("yscale", 1)))
            zscale = float(cast("float", raw.dxf.get("zscale", 1)))
            angle = float(cast("float", raw.dxf.get("rotation", 0)))
            if (
                not all(math.isfinite(value) for value in (xscale, yscale, zscale, angle))
                or min(xscale, yscale, zscale) <= 0
                or xscale != yscale
            ):
                raise ValueError("只支持正等比二维块实例")
            insert_x, insert_y, insert_z = _xyz(raw.dxf.get("insert"))
            layout = document.blocks.get(name)
            if layout is None:
                raise ValueError("块定义不存在")
            base_z, plane_z = plane_height(name, layout)
            world_z = insert_z + zscale * (plane_z - base_z)
            if not math.isfinite(world_z) or world_z != 0:
                raise ValueError("块实例不在图纸 XY 平面")
            position = (insert_x * scale, insert_y * scale)
            source_layer = str(raw.dxf.get("layer", "0"))
            layer = layers.get(layer_names[source_layer.lower()]).name
            if document.layers.get(source_layer).transparency > 0:
                raise ValueError(f"块实例图层 {source_layer} 的透明度无法保留")
            key = name.lower()
            if key in rejected:
                raise ValueError(rejected[key])
            definition = definitions.get(key)
            if definition is None:
                definition = read_definition(name)
            instance = BlockInstance(
                uuid4().hex, definition.definition_id, position, angle, xscale, layer
            )
            try:
                expand_block(definition, instance, styles or TextStyleTable())
            except (OverflowError, ValueError) as exc:
                raise ValueError(f"块实例无法展开：{exc}") from exc
            instances.append(instance)
            handles[instance.instance_id] = raw.dxf.handle
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            warnings.append(f"块实例 {raw.dxf.handle}（{name}）未导入：{exc}。")
    referenced_names = {
        str(item.dxf.get("name", "")).lower()
        for item in document.modelspace()
        if item.dxftype() == "INSERT"
    }
    referenced_names.update(
        str(item.dxf.get("geometry", "")).lower()
        for item in document.modelspace()
        if item.dxftype() in {"DIMENSION", "ARC_DIMENSION"}
    )
    if include_nested_referenced:
        # Special annotation block graphs belong to the annotation, even when
        # a descendant happens to look like an independently usable block.
        annotation_roots = {
            str(item.dxf.get("name", ""))
            for item in document.modelspace()
            if item.dxftype() == "INSERT" and _xdata_values(item, DATUM_APPID)
        }
        annotation_roots.update(
            str(item.dxf.get("geometry", ""))
            for item in document.modelspace()
            if item.dxftype() in {"DIMENSION", "ARC_DIMENSION"}
        )
        pending = list(annotation_roots)
        visited: set[str] = set()
        while pending:
            name = pending.pop()
            key = name.lower()
            if not key or key in visited:
                continue
            visited.add(key)
            referenced_names.add(key)
            layout = document.blocks.get(name)
            if layout is not None:
                pending.extend(
                    str(item.dxf.get("name", "")) for item in layout if item.dxftype() == "INSERT"
                )
    if not include_nested_referenced:
        for layout in document.blocks:
            referenced_names.update(
                str(item.dxf.get("name", "")).lower()
                for item in layout
                if item.dxftype() == "INSERT"
            )
    for layout in document.blocks:
        name = layout.name
        if (
            not name
            or name.startswith("*")
            or name.lower() in referenced_names
            or ARROWS.arrow_name(name) in ARROWS
        ):
            continue
        try:
            read_definition(name)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            warnings.append(f"块定义 {name} 未导入：{exc}。")
    return tuple(definitions.values()), tuple(instances), handles, styles, tuple(warnings)


def _read_mapped_datum(
    document: _Drawing,
    entity: _DxfEntity,
    metadata: tuple[str, ...],
    scale: float,
    layer_names: Mapping[str, str],
    warnings: list[str],
) -> DatumIdentifier:
    datum = read_datum(document, entity, metadata, scale, warnings=warnings)
    return replace(datum, layer_name=layer_names.get(datum.layer_name.lower(), "0"))


def _read_mapped_detached_dimension(
    entity: _DxfEntity, scale: float, layer_names: Mapping[str, str]
) -> DetachedDimension:
    dimension = read_detached_dimension(entity, scale)
    return replace(dimension, layer_name=layer_names.get(dimension.layer_name.lower(), "0"))


def _map_associated_dimension_layer(
    constraint: SketchConstraint,
    native: _DxfEntity,
    sketch: Sketch,
    layer_names: Mapping[str, str],
) -> SketchConstraint:
    native_layer = layer_names.get(str(native.dxf.layer).lower(), "0")
    first_id = constraint.references[0].entity_id if constraint.references else None
    first = next((entity for entity in sketch.entities if entity.entity_id == first_id), None)
    if constraint.layer_name is None and first is not None and first.layer_name == native_layer:
        return constraint
    return replace(constraint, layer_name=native_layer)


def read_sketch_dxf(
    path: Path, *, unit_override: str | None = None, include_nested_referenced_blocks: bool = False
) -> DxfSketchImport:
    """Read 2D linework into one XY sketch; unsupported entities are reported."""
    document = _read_dxf_file(path)
    scale, unit_name = _unit_scale(document.header.get("$INSUNITS", 0), unit_override)
    warnings: list[str] = []
    layers, known_layer_names = _read_layers(document, warnings)
    text_handles: dict[str, str] = {}
    texts, text_styles, text_warnings = read_texts_dxf(document, scale, handle_map=text_handles)
    texts = tuple(
        replace(item, layer_name=known_layer_names.get(item.layer_name.lower(), "0"))
        for item in texts
    )
    geometry_handles: list[tuple[str, str]] = []
    warnings.extend(text_warnings)
    entities: list[SketchEntity] = []
    fallback_text_entities: list[object] = []
    dimension_mappings: list[tuple[str, object, _DxfEntity]] = []
    tolerance_frames: list[FeatureControlFrame] = []
    datum_identifiers: list[DatumIdentifier] = []
    pending_datums: list[tuple[DatumIdentifier, _DxfEntity]] = []
    pending_inserts: list[_DxfEntity] = []
    detached_dimensions: list[DetachedDimension] = []
    detached_handles: list[str] = []
    associated_handles: list[tuple[str, str]] = []
    frame_handle_records: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    known_sketch_ids: set[str] = set()
    used_entity_ids: set[str] = set()
    entity_id_map: dict[tuple[str, str], str | None] = {}
    unverified_curve_ids: set[tuple[str, str]] = set()
    point_id_owners: dict[str, tuple[int, tuple[str, str] | None]] = {}
    modelspace = document.modelspace()
    frame_identity_counts = _frame_metadata_identity_counts(modelspace)
    frame_leaders: dict[str, list[_Leader]] = {}
    native_frame_leaders: dict[str, list[_Leader]] = {}
    unlinked_leaders: list[_Leader] = []
    tolerance_handles = {str(item.dxf.handle) for item in modelspace.query("TOLERANCE")}
    handled_frame_leaders: set[str] = set()
    surface_extensions: dict[tuple[str, str], list[_DxfEntity]] = {}
    surface_indications: dict[tuple[str, str], dict[int, list[_DxfEntity]]] = {}
    for candidate in modelspace:
        indication_marker = _xdata_values(candidate, _SURFACE_INDICATION_APPID)
        if indication_marker:
            if (
                len(indication_marker) == 3
                and indication_marker[0] in ("datum", "frame")
                and _is_identity(indication_marker[1])
                and indication_marker[2].isdigit()
                and len(indication_marker[2]) < 5
            ):
                key = (indication_marker[0], indication_marker[1])
                surface_indications.setdefault(key, {}).setdefault(
                    int(indication_marker[2]), []
                ).append(candidate)
            else:
                warnings.append("表面指示图形身份无效，无法恢复关联。")
                surface_indications.setdefault(
                    ("invalid", str(candidate.dxf.handle)), {}
                ).setdefault(0, []).append(candidate)
        marker = _xdata_values(candidate, _SURFACE_EXTENSION_APPID)
        if len(marker) == 2 and marker[0] in ("datum", "frame") and _is_identity(marker[1]):
            surface_extensions.setdefault((marker[0], marker[1]), []).append(candidate)
        elif marker:
            warnings.append("表面延伸线身份无效，无法恢复关联。")
            surface_extensions.setdefault(("invalid", str(candidate.dxf.handle)), []).append(
                candidate
            )
    for raw_leader in modelspace.query("LEADER"):
        leader = cast("_Leader", raw_leader)
        if _xdata_values(leader, _SURFACE_INDICATION_APPID) or _xdata_values(
            leader, _SURFACE_EXTENSION_APPID
        ):
            continue
        marker = _xdata_values(leader, _FCF_LEADER_APPID)
        annotation_handle = str(leader.dxf.get("annotation_handle", "") or "")
        if annotation_handle in tolerance_handles:
            native_frame_leaders.setdefault(annotation_handle, []).append(leader)
        elif not marker:
            unlinked_leaders.append(leader)
        if len(marker) == 1:
            frame_leaders.setdefault(marker[0], []).append(leader)
        elif marker:
            warnings.append(f"公差框引线 {leader.dxf.handle} 的标识无效，无法恢复。")
            frame_leaders.setdefault(f"invalid:{leader.dxf.handle}", []).append(leader)
    for entity in modelspace:
        if _xdata_values(entity, _SURFACE_INDICATION_APPID):
            continue
        if _xdata_values(entity, _SURFACE_EXTENSION_APPID):
            continue
        if entity.dxftype() == "LEADER":
            continue
        datum_metadata = _xdata_values(entity, DATUM_APPID) if entity.dxftype() == "INSERT" else ()
        if datum_metadata:
            try:
                datum = _read_mapped_datum(
                    document, entity, datum_metadata, scale, known_layer_names, warnings
                )
                pending_datums.append((datum, entity))
            except (
                DXFTableEntryError,
                TypeError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
            ) as exc:
                warnings.append(f"基准图形块 {entity.dxf.handle} 无法导入：{exc}")
                _preserve_datum_block_graphics(
                    entity, scale, known_layer_names, entities, fallback_text_entities, warnings
                )
            continue
        if entity.dxftype() == "INSERT":
            pending_inserts.append(entity)
            continue
        if entity.dxftype() in ("TEXT", "MTEXT"):
            continue
        if entity.dxftype() == "TOLERANCE":
            frame_warnings: list[str] = []
            try:
                content = entity.dxf.get("content", "")
                if not isinstance(content, str):
                    raise ValueError("公差框内容无效")
                if len(content.encode("utf-8")) > 255:
                    warnings.append(
                        f"TOLERANCE {entity.dxf.handle} 内容长度超过 255 字节，其他 CAD 可能无法打开。"
                    )
                normal = cast("Sequence[float]", entity.dxf.get("extrusion", (0, 0, 1)))
                if (
                    len(normal) != 3
                    or not all(math.isfinite(value) for value in normal)
                    or math.dist(normal, (0, 0, 1)) > 1e-9
                ):
                    raise ValueError("只支持 XY 平面的形位公差框")
                rows = decode_rows(content)
                if normalize_legacy_negative_zero(content) != content:
                    frame_warnings.append(f"TOLERANCE {entity.dxf.handle} 的负零已按零导入。")
                if re.search(r"%%[vV](?:\{\\(?i:Fgdt);n\})?\.\d", content):
                    frame_warnings.append(
                        f"TOLERANCE {entity.dxf.handle} 的前导零省略格式未保留；已按数值和精度导入。"
                    )
                position = _xy(entity.dxf.get("insert"), scale)
                axis = _xy(entity.dxf.get("x_axis_vector", (1, 0, 0)), 1.0)
                if math.hypot(*axis) < 1e-12:
                    raise ValueError("公差框方向无效")
                rotation = math.degrees(math.atan2(axis[1], axis[0])) % 360
                identity = uuid4().hex
                source_style_id: str | None = None
                implicit_font: TextStyle | None = None
                explicit_font: tuple[TextStyle, TextStyle] | None = None
                metadata_valid = False
                source_frame: FeatureControlFrame | None = None
                metadata = _xdata_values(entity, _FCF_APPID)
                if metadata:
                    try:
                        raw: object = json.loads(unpack_annotation_metadata(metadata))
                        if not isinstance(raw, Mapping):
                            raise ValueError("形位公差元数据格式无效")
                        mapping = cast("Mapping[str, object]", raw)
                        if not isinstance(mapping.get("frame"), Mapping):
                            raise ValueError("形位公差元数据缺少对象")
                        source = FeatureControlFrame.from_mapping(mapping["frame"])
                        source_frame = source
                        saved_content = mapping.get("content")
                        if not isinstance(saved_content, str) or encode_rows(
                            source.rows, allow_hidden=True
                        ) != normalize_legacy_negative_zero(saved_content):
                            raise ValueError("形位公差元数据与其保存的原生内容不一致")
                        parsed_font = (
                            TextStyle.from_mapping(mapping["implicit_font"])
                            if source.text_style_id is None and "implicit_font" in mapping
                            else None
                        )
                        identity = source.frame_id
                        source_style_id = source.text_style_id
                        implicit_font = parsed_font
                        explicit_mapping = mapping.get("explicit_font")
                        if source_style_id is not None and "explicit_font" in mapping:
                            try:
                                if not isinstance(explicit_mapping, Mapping):
                                    raise ValueError("文字样式快照格式无效")
                                font_data = cast("Mapping[str, object]", explicit_mapping)
                                saved_font = TextStyle.from_mapping(font_data.get("source"))
                                native_font = TextStyle.from_mapping(font_data.get("native"))
                                if saved_font.style_id != source_style_id:
                                    raise ValueError("文字样式身份不一致")
                                explicit_font = (saved_font, native_font)
                            except (TypeError, ValueError, KeyError):
                                frame_warnings.append("公差框文字样式快照无效，将采用原生样式。")
                        if math.isclose(
                            (rotation - source.rotation_deg) % 360, 0.0, abs_tol=1e-9
                        ) or math.isclose(
                            (rotation - source.rotation_deg) % 360, 360.0, abs_tol=1e-9
                        ):
                            rotation = source.rotation_deg
                        if mapping.get("content") == content:
                            rows = source.rows
                        else:
                            frame_warnings.append(
                                f"形位公差 {identity[:8]} 原生内容已修改；基准关联需重建"
                            )
                        metadata_valid = True
                    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                        frame_warnings.append(
                            f"TOLERANCE {entity.dxf.handle} 的 MyCAD 元数据无效，"
                            f"已按原生内容导入且基准关联需重建：{exc}"
                        )
                if scale != 1:
                    rows = tuple(
                        replace(
                            row,
                            value=row.value * scale,
                            precision=scaled_length_precision(row.precision, scale),
                        )
                        for row in rows
                    )
                if any(row.precision_insufficient for row in rows):
                    frame_warnings.append(
                        f"形位公差 {identity[:8]} 的精度不足，非零公差按原精度显示为零；精确数值已保留。"
                    )
                layer = known_layer_names.get(str(entity.dxf.layer).lower(), "0")
                imported_style_id, text_styles = _read_frame_text_style(
                    document,
                    entity,
                    scale,
                    text_styles,
                    source_style_id,
                    implicit_font,
                    explicit_font,
                    metadata_valid,
                    frame_warnings,
                )
                previously_handled = set(handled_frame_leaders)
                (
                    leader_target,
                    leader_offsets,
                    leader_anchor,
                    leader_attachment,
                    leader_annotation_attachment,
                    surface_indication,
                    leader_auto_normal,
                ) = _read_frame_leader(
                    metadata_valid,
                    source_frame,
                    frame_leaders,
                    frame_identity_counts,
                    handled_frame_leaders,
                    position,
                    scale,
                    rotation,
                    entity,
                    identity,
                    frame_warnings,
                )
                native_candidates = native_frame_leaders.get(str(entity.dxf.handle), [])
                if leader_target is None and (
                    source_frame is None or not frame_leaders.get(source_frame.frame_id)
                ):
                    native = _read_native_frame_leader(
                        native_candidates, position, scale, entity, identity, frame_warnings
                    )
                    if native is not None:
                        leader_target, leader_offsets, leader_anchor = native
                        handled_frame_leaders.add(str(native_candidates[0].dxf.handle))
                tolerance_frames.append(
                    _restore_legacy_auto_route(
                        metadata,
                        source_frame,
                        FeatureControlFrame(
                            identity,
                            rows,
                            position,
                            rotation,
                            layer,
                            imported_style_id,
                            leader_target,
                            leader_offsets,
                            leader_anchor,
                            leader_attachment,
                            leader_annotation_attachment,
                            surface_indication,
                            leader_auto_normal,
                            _retain_auto_route(
                                source_frame,
                                metadata_valid,
                                leader_auto_normal,
                                leader_offsets,
                                scale,
                            ),
                            _retain_route_crossing_policy(
                                source_frame,
                                metadata_valid,
                                leader_auto_normal,
                                leader_offsets,
                                scale,
                            ),
                            _retain_route_target_tracking(
                                source_frame,
                                metadata_valid,
                                leader_auto_normal,
                                leader_offsets,
                                scale,
                            ),
                            _retain_route_algorithm_version(
                                source_frame,
                                metadata_valid,
                                leader_auto_normal,
                                leader_offsets,
                                scale,
                            ),
                            leader_arrow_style=_read_frame_arrow_style(
                                source_frame, metadata_valid
                            ),
                        ),
                        frame_warnings,
                        scale,
                        frame_identity_counts.get(identity, 0) == 1,
                    )
                )
                matched_leaders = tuple(sorted(handled_frame_leaders - previously_handled))
                frame_handle_records.setdefault(identity, []).append(
                    (entity.dxf.handle, matched_leaders)
                )
                warnings.extend(frame_warnings)
            except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                warnings.append(f"TOLERANCE {entity.dxf.handle} 无法导入：{exc}")
            continue
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
                try:
                    dimension = _read_mapped_detached_dimension(entity, scale, known_layer_names)
                    metadata = _xdata_values(entity, REFERENCE_DIMENSION_APPID)
                    if metadata and _is_identity(metadata[0]):
                        dimension = replace(dimension, dimension_id=metadata[0])
                    warnings.extend(
                        ordinate_axis_snapshot_warnings(metadata, dimension, str(entity.dxf.handle))
                    )
                    angular_unit = (
                        int(
                            cast(
                                "int",
                                cast("_NativeDimension", entity).override().get("dimaunit", 0),
                            )
                        )
                        if dimension.kind in ("angular_2l", "angular_3p")
                        else 0
                    )
                    detached_dimensions.append(dimension)
                    detached_handles.append(entity.dxf.handle)
                    warnings.append(
                        f"外部 DIMENSION {entity.dxf.handle} 作为参考尺寸导入，不关联几何；部分原样式和显示方式不保留。"
                    )
                    if dimension.kind == "angular_2l":
                        warnings.append(
                            f"两线角度 {entity.dxf.handle} 按交点和方向重建，原始线端位置不保留。"
                        )
                    if dimension.kind in ("angular_2l", "angular_3p"):
                        graphics = angular_dimension_graphics(entity)
                        if graphics is None:
                            warnings.append(
                                f"尺寸图形不可核对：DIMENSION {entity.dxf.handle} 的图形块缺失、"
                                "不可读取或仅含辅助内容；"
                                "已按定义和公差字段导入，请核对来源文件。"
                            )
                        elif not angular_dimension_has_inspectable_arc(graphics, dimension, scale):
                            warnings.append(
                                f"角度弧线不可核对：DIMENSION {entity.dxf.handle} 无法找到可核对的"
                                "原生圆弧；请对照来源文件检查角度方向。"
                            )
                        if angular_graphic_omits_tolerance(entity, dimension):
                            warnings.append(
                                f"尺寸图形未显示公差：DIMENSION {entity.dxf.handle} 含公差字段，"
                                "但原图形仅显示名义角度；已读取公差，请核对来源文件。"
                            )
                    if angular_unit:
                        original = {1: "度分秒", 2: "百分度", 3: "弧度", 4: "测量方位角"}.get(
                            angular_unit, f"代码 {angular_unit}"
                        )
                        warnings.append(
                            f"角度尺寸 {entity.dxf.handle} 的角度显示单位 {original} "
                            "不保留，导入后以十进制度显示，最多 8 位小数，可能舍入。"
                        )
                    if tolerance_values_hidden_by_precision(dimension.nominal, dimension.tolerance):
                        warnings.append(
                            f"尺寸 {entity.dxf.handle} 的非零公差按设置精度将显示为零或不同上下限显示相同；画布提示公差精度不足。"
                        )
                except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
                    warnings.append(
                        f"外部 DIMENSION {entity.dxf.handle} 没有关联的 MyCAD 图元引用，未导入其语义：{exc}"
                    )
            continue
        legacy_construction_layer = layer_name.upper() == _CONSTRUCTION_LAYER and len(values) < 5
        restored_layer_name = (
            "0" if legacy_construction_layer else known_layer_names.get(layer_name.lower(), "0")
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
                values[5] if len(values) >= 6 else "",
            )
        except ValueError as exc:
            warnings.append(f"{entity.dxftype()} {entity.dxf.handle} 已跳过：{exc}")
            continue
        if parsed is None:
            warnings.append(
                f"{entity.dxftype()} {entity.dxf.handle}（图层 {entity.dxf.layer}）不在支持子集中，已跳过"
            )
            continue
        parsed = _restore_imported_curve_ids(
            entity, parsed, values, scale, entities, warnings, unverified_curve_ids, point_id_owners
        )
        entities.append(parsed)
        geometry_handles.append((parsed.entity_id, entity.dxf.handle))
        used_entity_ids.add(entity_id)
        if len(values) >= 2 and _is_identity(values[0]) and _is_identity(values[1]):
            key = (values[0], values[1])
            entity_id_map[key] = None if key in entity_id_map else entity_id

    datum_identifiers, text_styles = _finalize_datum_imports(
        document,
        pending_datums,
        scale,
        text_styles,
        known_layer_names,
        entities,
        fallback_text_entities,
        warnings,
    )
    if fallback_text_entities:
        texts, text_styles = _merge_datum_fallback_texts(
            document, scale, fallback_text_entities, texts, text_styles, warnings
        )

    for candidates in frame_leaders.values():
        for leader in candidates:
            if str(leader.dxf.handle) not in handled_frame_leaders:
                warnings.append(
                    f"公差框引线 {leader.dxf.handle} 未能安全匹配公差框，无法恢复关联。"
                )
                _preserve_unmatched_frame_leader(
                    leader, scale, known_layer_names, entities, warnings
                )
    for candidates in native_frame_leaders.values():
        for leader in candidates:
            if (
                not _xdata_values(leader, _FCF_LEADER_APPID)
                and str(leader.dxf.handle) not in handled_frame_leaders
            ):
                warnings.append(f"公差框原生引线 {leader.dxf.handle} 无法唯一恢复关联。")
                _preserve_unmatched_frame_leader(
                    leader, scale, known_layer_names, entities, warnings
                )
    for leader in unlinked_leaders:
        _preserve_unmatched_frame_leader(leader, scale, known_layer_names, entities, warnings)
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

    verified_indications = _validate_surface_indications(
        datum_identifiers, tolerance_frames, surface_indications, scale, warnings
    )

    resolved_datums: list[DatumIdentifier] = []
    entities_by_id = {entity.entity_id: entity for entity in entities}
    normal_sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), tuple(entities), layers=layers)
    used_surface_extensions: set[tuple[str, str]] = set()
    restored_surface_extensions: set[tuple[str, str]] = set()
    surface_owner_counts: dict[tuple[str, str], int] = {}
    for owner, identity in [
        *(("datum", item.datum_id) for item in datum_identifiers),
        *(("frame", item.frame_id) for item in tolerance_frames),
    ]:
        key = (owner, identity)
        surface_owner_counts[key] = surface_owner_counts.get(key, 0) + 1

    def restore_geometry_attachment(
        attachment: DatumAttachment, owner: str, identity: str, target_point: Point2D | None
    ) -> DatumAttachment | None:
        source_key = (attachment.sketch_id, attachment.reference.entity_id)
        if source_key in unverified_curve_ids:
            return None
        target_id = entity_id_map.get(source_key)
        if target_id is None or target_id not in entities_by_id:
            return None
        reference = replace(attachment.reference, entity_id=target_id)
        extension = attachment.surface_extension
        if extension is not None:
            try:
                extension = replace(
                    extension,
                    distance_mm=extension.distance_mm * scale,
                    offset_mm=extension.offset_mm * scale,
                    overshoot_mm=extension.overshoot_mm * scale,
                )
            except ValueError:
                return None
        candidate = replace(
            attachment, sketch_id=sketch_id, reference=reference, surface_extension=extension
        )
        target = resolve_attachment_local(candidate, entities_by_id)
        if target is None or target_point is None or math.dist(target, target_point) > 1e-7:
            return None
        if extension is not None:
            key = (owner, identity)
            matches = surface_extensions.get(key, [])
            used_surface_extensions.add(key)
            if surface_owner_counts.get(key) != 1:
                return None
            try:
                kind, expected, _ = _surface_extension_dxf_geometry(
                    candidate, entities_by_id[target_id]
                )
            except ValueError:
                return None
            if len(matches) != 1 or not _surface_extension_matches(
                matches[0], kind, expected, scale
            ):
                return None
            restored_surface_extensions.add(key)
        return candidate

    resolved_frames: list[FeatureControlFrame] = []
    for frame in tolerance_frames:
        attachment = frame.leader_attachment
        if attachment is not None:
            restored = restore_geometry_attachment(
                attachment, "frame", frame.frame_id, frame.leader_target_mm
            )
            if restored is None:
                warnings.append(f"形位公差 {frame.frame_id[:8]} 的引线附着无法恢复，已解除关联。")
                frame = replace(
                    frame,
                    leader_attachment=None,
                    leader_auto_normal=False,
                    leader_auto_route=False,
                    route_avoid_crossing=False,
                    route_track_target=False,
                    route_algorithm_version=1,
                    surface_indication=(
                        replace(
                            frame.surface_indication,
                            auto_normal=False,
                            auto_route=False,
                            route_avoid_crossing=False,
                        )
                        if frame.surface_indication is not None
                        else None
                    ),
                )
            else:
                frame = replace(frame, leader_attachment=restored)
                target = frame.leader_target_mm
                if target is not None and frame.leader_auto_normal:
                    offset = frame.leader_offsets[-1]
                    vertex = (frame.position_mm[0] + offset[0], frame.position_mm[1] + offset[1])
                    if not _imported_normal_is_valid(restored, normal_sketch, target, vertex):
                        frame = replace(
                            frame,
                            leader_auto_normal=False,
                            leader_auto_route=False,
                            route_avoid_crossing=False,
                            route_track_target=False,
                            route_algorithm_version=1,
                        )
                        warnings.append(
                            f"形位公差 {frame.frame_id[:8]} 的法向已改变，已解除法向约束。"
                        )
                indication = frame.surface_indication
                if target is not None and indication is not None and indication.auto_normal:
                    offset = indication.leader_offsets_mm[0]
                    vertex = (target[0] + offset[0], target[1] + offset[1])
                    if not _imported_normal_is_valid(restored, normal_sketch, target, vertex):
                        frame = replace(
                            frame,
                            surface_indication=replace(
                                indication,
                                auto_normal=False,
                                auto_route=False,
                                route_avoid_crossing=False,
                            ),
                        )
                        warnings.append(
                            f"形位公差 {frame.frame_id[:8]} 的表面法向已改变，已解除法向约束。"
                        )
        resolved_frames.append(frame)
    tolerance_frames = resolved_frames
    for datum in datum_identifiers:
        attachment = datum.attachment
        if attachment is not None:
            restored = restore_geometry_attachment(
                attachment, "datum", datum.datum_id, datum.target_mm
            )
            if restored is None:
                warnings.append(
                    f"基准 {datum.label} 的附着目标无法唯一恢复或已被修改，已保留位置并解除关联"
                )
                datum = replace(
                    datum,
                    attachment=None,
                    leader_auto_normal=False,
                    leader_auto_route=False,
                    route_avoid_crossing=False,
                    route_track_target=False,
                    route_algorithm_version=1,
                    spline_normal_enabled=False,
                    surface_indication=(
                        replace(
                            datum.surface_indication,
                            auto_normal=False,
                            auto_route=False,
                            route_avoid_crossing=False,
                        )
                        if datum.surface_indication is not None
                        else None
                    ),
                )
            else:
                datum = replace(datum, attachment=restored)
                if datum.leader_auto_normal:
                    offset = datum.leader_offsets[-1]
                    vertex = (datum.position_mm[0] + offset[0], datum.position_mm[1] + offset[1])
                    if not _imported_normal_is_valid(
                        restored, normal_sketch, datum.target_mm, vertex
                    ):
                        datum = replace(
                            datum,
                            leader_auto_normal=False,
                            leader_auto_route=False,
                            route_avoid_crossing=False,
                            route_track_target=False,
                            route_algorithm_version=1,
                        )
                        warnings.append(f"基准 {datum.label} 的法向已改变，已解除法向约束。")
                indication = datum.surface_indication
                if indication is not None and indication.auto_normal:
                    offset = indication.leader_offsets_mm[0]
                    vertex = (datum.target_mm[0] + offset[0], datum.target_mm[1] + offset[1])
                    if not _imported_normal_is_valid(
                        restored, normal_sketch, datum.target_mm, vertex
                    ):
                        datum = replace(
                            datum,
                            surface_indication=replace(
                                indication,
                                auto_normal=False,
                                auto_route=False,
                                route_avoid_crossing=False,
                            ),
                        )
                        warnings.append(f"基准 {datum.label} 的表面法向已改变，已解除法向约束。")
        resolved_datums.append(datum)
    datum_identifiers = resolved_datums
    for owner, identity in surface_extensions.keys() - used_surface_extensions:
        warnings.append(f"表面延伸线 {owner} {identity[:8]} 没有可恢复的标注关联。")
    for key in surface_extensions.keys() - restored_surface_extensions:
        for entity in surface_extensions[key]:
            layer_name = str(entity.dxf.layer)
            layer = known_layer_names.get(layer_name.lower(), "0")
            entity_id = uuid4().hex
            try:
                parsed = _read_entity(entity, entity_id, "", "ccw", scale, layer, False, "")
            except (TypeError, ValueError, OverflowError) as exc:
                warnings.append(f"表面延伸图形无法保留：{exc}")
                continue
            if parsed is not None:
                entities.append(parsed)
                warnings.append("失关联的表面延伸线已作为普通图元保留。")
            else:
                warnings.append("失关联的表面延伸图形类型不受支持，无法保留。")
    _preserve_unverified_surface_indications(
        surface_indications, verified_indications, known_layer_names, scale, entities, warnings
    )

    entity_ids = {entity.entity_id for entity in entities}
    measurement_sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), tuple(entities), layers=layers)
    constraints: list[SketchConstraint] = []
    imported_styles: list[tuple[str, DimensionStyle]] = []
    seen_constraint_ids: set[str] = set()
    seen_constraint_sources: set[tuple[str, str]] = set()
    dimension_id_map: dict[tuple[str, str], str | None] = {}
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
                precision=(
                    scaled_length_precision(constraint.precision, scale)
                    if constraint.unit == "mm"
                    else constraint.precision
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
                tolerance=(
                    replace(
                        constraint.tolerance,
                        upper_deviation=constraint.tolerance.upper_deviation * scale,
                        lower_deviation=constraint.tolerance.lower_deviation * scale,
                        precision=scaled_length_precision(constraint.tolerance.precision, scale),
                    )
                    if constraint.tolerance is not None and constraint.unit == "mm"
                    else constraint.tolerance
                ),
            )
            try:
                native_changes = _dimension_snapshot_changes(native_dimension)
                if native_changes is None and _DIMENSION_SNAPSHOT_APPID in document.appids:
                    native_warnings.append("原生标注快照缺失，无法检查外部修改")
            except (TypeError, ValueError, json.JSONDecodeError):
                native_changes = None
                native_warnings.append("原生标注快照无效，无法检查外部修改")
            snapshot_values_for_tolerance = _xdata_values(
                native_dimension, _DIMENSION_SNAPSHOT_APPID
            )
            tolerance_snapshot_unavailable = native_changes is None or bool(
                snapshot_values_for_tolerance and snapshot_values_for_tolerance[0] == "1"
            )
            if tolerance_snapshot_unavailable:
                constraint, recovery_warnings = _recover_unverified_native_dimension(
                    constraint, native_dimension, scale
                )
                native_warnings.extend(recovery_warnings)
            if native_changes:
                remaining_changes = set(native_changes)
                tolerance_keys = {
                    f"style:{name}"
                    for name in (
                        "dimtol",
                        "dimlim",
                        "dimtp",
                        "dimtm",
                        "dimtfac",
                        "dimtdec",
                        "dimtolj",
                    )
                }
                if constraint.kind == "angle":
                    tolerance_keys.add("style:dimaunit")
                if remaining_changes & tolerance_keys:
                    style = cast("_NativeDimension", native_dimension).override()
                    try:
                        enabled = int(cast("int", style.get("dimtol", 0)))
                        limits = int(cast("int", style.get("dimlim", 0)))
                        if enabled not in (0, 1) or limits not in (0, 1) or enabled + limits > 1:
                            raise ValueError("unsupported tolerance mode")
                        upper = float(cast("float", style.get("dimtp", 0.0)))
                        lower = -float(cast("float", style.get("dimtm", 0.0)))
                        angular_unit = int(cast("int", style.get("dimaunit", 0)))
                        factor = (
                            scale
                            if constraint.unit == "mm"
                            else angular_tolerance_factor_to_degrees(angular_unit)
                        )
                        mode = (
                            "limits"
                            if limits
                            else "symmetric"
                            if enabled and upper == -lower and upper >= 0
                            else "deviation"
                            if enabled
                            else "none"
                        )
                        if (
                            mode == "symmetric"
                            and constraint.tolerance is not None
                            and constraint.tolerance.mode == "deviation"
                        ):
                            mode = "deviation"
                        alignment = {0: "bottom", 1: "middle", 2: "top"}[
                            int(cast("int", style.get("dimtolj", 1)))
                        ]
                        tolerance = DimensionTolerance(
                            mode,
                            upper * factor,
                            lower * factor,
                            angular_precision_in_degrees(
                                angular_unit, int(cast("int", style.get("dimtdec", 2)))
                            )
                            if constraint.kind == "angle"
                            else scaled_length_precision(
                                int(cast("int", style.get("dimtdec", 2))), scale
                            ),
                            float(cast("float", style.get("dimtfac", 1.0))),
                            alignment,
                        )
                        constraint = replace(constraint, tolerance=tolerance)
                        remaining_changes.difference_update(tolerance_keys)
                        native_warnings.append(
                            f"尺寸 {constraint.constraint_id[:8]} 的外部公差设置已恢复"
                        )
                        if constraint.kind == "angle" and angular_unit:
                            native_warnings.append(
                                f"尺寸 {constraint.constraint_id[:8]} 的角度显示单位不保留，导入后以十进制度显示，最多 8 位小数，可能舍入。"
                            )
                    except (ValueError, TypeError, OverflowError, KeyError) as exc:
                        raise ValueError("外部公差不受支持，不能安全恢复标注") from exc
                precision_key = "style:dimadec" if constraint.kind == "angle" else "style:dimdec"
                if precision_key in remaining_changes or (
                    constraint.kind == "angle" and "style:dimaunit" in native_changes
                ):
                    style = cast("_NativeDimension", native_dimension).override()
                    precision = style.get(precision_key.removeprefix("style:"))
                    if constraint.kind == "angle" and precision == -1:
                        precision = style.get("dimdec", 2)
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
                        unit_value = style.get("dimaunit", 0)
                        if constraint.kind != "angle" or (
                            isinstance(unit_value, int) and unit_value in (0, 1, 2, 3)
                        ):
                            if constraint.kind == "angle" and isinstance(unit_value, int):
                                precision = angular_precision_in_degrees(unit_value, precision)
                            elif constraint.unit == "mm":
                                precision = scaled_length_precision(precision, scale)
                            constraint = replace(constraint, precision=precision)
                            remaining_changes.discard(precision_key)
                            native_warnings.append(
                                f"尺寸 {constraint.constraint_id[:8]} 的外部精度设置已恢复"
                            )
                if (
                    remaining_changes & {"text_midpoint", "dimtype"}
                    and "extrusion" not in remaining_changes
                ):
                    if not cast("int", native_dimension.dxf.get("dimtype", 0)) & 128:
                        constraint = replace(constraint, text_position_mm=None)
                        remaining_changes.discard("text_midpoint")
                        native_warnings.append(
                            f"尺寸 {constraint.constraint_id[:8]} 的外部默认文字位置已重算，使用自动定位"
                        )
                    else:
                        try:
                            position = _xy(native_dimension.dxf.get("text_midpoint"), scale)
                        except ValueError:
                            pass
                        else:
                            constraint = replace(constraint, text_position_mm=position)
                            remaining_changes.discard("text_midpoint")
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
                        or snapshot_values[0] not in ("3", "4", "5", "6", "7", "8")
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
                    if candidate.text_style_id is not None:
                        try:
                            native_font = (
                                cast("_NativeDimension", native_dimension)
                                .override()
                                .get("dimtxsty", "")
                            )
                            if not isinstance(native_font, str) or not native_font:
                                raise ValueError("原生文字样式不存在")
                            font = read_dxf_text_style(document, native_font, scale)
                            if text_styles is None:
                                text_styles = TextStyleTable((font,), font.style_id)
                            elif all(item.style_id != font.style_id for item in text_styles.styles):
                                text_styles = replace(
                                    text_styles, styles=(*text_styles.styles, font)
                                )
                            candidate = replace(candidate, text_style_id=font.style_id)
                        except (DXFTableEntryError, KeyError, TypeError, ValueError) as exc:
                            candidate = replace(candidate, text_style_id=None)
                            native_warnings.append(f"尺寸文字样式引用未恢复：{exc}")
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
            if constraint.tolerance is None and imported_style is None:
                try:
                    restored_tolerance = read_native_tolerance(
                        cast("_NativeDimension", native_dimension).override(),
                        angular=constraint.kind == "angle",
                        scale=scale,
                    )
                    if (
                        restored_tolerance.mode != "none"
                        or constraint.style_name is not None
                        or bool(style_values)
                    ):
                        constraint = replace(constraint, tolerance=restored_tolerance)
                        native_warnings.append(
                            f"尺寸 {constraint.constraint_id[:8]} 的样式无法恢复，已按原生值恢复为单尺寸公差覆盖。"
                        )
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError("外部公差不受支持，不能安全恢复标注") from exc
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
                dimension_id_map[source_key] = None
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
        displayed_tolerance = constraint.tolerance
        if displayed_tolerance is None and imported_style is not None:
            displayed_tolerance = (
                imported_style.angular_tolerance
                if constraint.kind == "angle"
                else imported_style.linear_tolerance
            )
        if (
            displayed_tolerance is not None
            and constraint.value is not None
            and tolerance_values_hidden_by_precision(constraint.value, displayed_tolerance)
        ):
            warnings.append(
                f"尺寸 {constraint.constraint_id[:8]} 的非零公差按设置精度将显示为零或不同上下限显示相同；画布提示公差精度不足。"
            )
        if constraint.kind == "angle":
            native_style = cast("_NativeDimension", native_dimension).override()
            if (
                native_style.get("dimtol", 0) == 1 or native_style.get("dimlim", 0) == 1
            ) and angular_graphic_shows_only_nominal(native_dimension):
                warnings.append(
                    f"尺寸图形未显示公差：尺寸 {constraint.constraint_id[:8]} 的原图形仅显示名义角度；"
                    "请核对来源文件。"
                )
        constraints.append(
            _map_associated_dimension_layer(
                constraint, native_dimension, measurement_sketch, known_layer_names
            )
        )
        associated_handles.append((constraint.constraint_id, native_dimension.dxf.handle))
        if imported_style is not None:
            imported_styles.append((constraint.constraint_id, imported_style))
        warnings.extend(native_warnings)
        if refreshed_value:
            warnings.append(f"参考尺寸 {constraint.constraint_id[:8]} 已按导入几何更新")
        seen_constraint_ids.add(constraint.constraint_id)
        seen_constraint_sources.add(source_key)
        dimension_id_map[source_key] = constraint.constraint_id

    sketch = Sketch(
        sketch_id,
        WorkPlaneFrame.xy(),
        tuple(entities),
        constraints=tuple(constraints),
        layers=layers,
    )
    counts: dict[str, int] = {}
    for datum in datum_identifiers:
        counts[datum.datum_id] = counts.get(datum.datum_id, 0) + 1
    ambiguous_ids = {identity for identity, count in counts.items() if count > 1}
    reserved_ids = set(counts)
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    unique_datums: list[DatumIdentifier] = []
    for datum in datum_identifiers:
        if datum.label.casefold() in seen_labels:
            warnings.append(f"基准名称 {datum.label} 重复；该基准已跳过，引用需重建。")
            continue
        if datum.datum_id in seen_ids:
            identity = uuid4().hex
            while identity in reserved_ids:
                identity = uuid4().hex
            reserved_ids.add(identity)
            warnings.append(f"基准身份 {datum.datum_id[:8]} 重复；已重新分配身份，引用需重建。")
            datum = replace(datum, datum_id=identity)
        seen_ids.add(datum.datum_id)
        seen_labels.add(datum.label.casefold())
        unique_datums.append(datum)
    datum_identifiers = unique_datums
    imported_datums: dict[str, DatumIdentifier | None] = {
        datum.datum_id: None if datum.datum_id in ambiguous_ids else datum
        for datum in datum_identifiers
    }
    all_annotation_ids = (
        {datum.datum_id for datum in datum_identifiers}
        | {dimension.dimension_id for dimension in detached_dimensions}
        | {frame.frame_id for frame in tolerance_frames}
    )
    used_annotation_ids = {datum.datum_id for datum in datum_identifiers}
    original_dimensions = tuple(detached_dimensions)
    unique_dimensions: list[DetachedDimension] = []
    for dimension in detached_dimensions:
        if dimension.dimension_id in used_annotation_ids:
            identity = uuid4().hex
            while identity in all_annotation_ids:
                identity = uuid4().hex
            all_annotation_ids.add(identity)
            warnings.append(f"参考尺寸身份 {dimension.dimension_id[:8]} 重复；已重新分配身份。")
            dimension = replace(dimension, dimension_id=identity)
        used_annotation_ids.add(dimension.dimension_id)
        unique_dimensions.append(dimension)
    detached_dimensions = unique_dimensions
    original_frames = tuple(tolerance_frames)
    restored_frames: list[FeatureControlFrame] = []
    for frame in tolerance_frames:
        if frame.frame_id in used_annotation_ids:
            identity = uuid4().hex
            while identity in all_annotation_ids:
                identity = uuid4().hex
            all_annotation_ids.add(identity)
            warnings.append(f"公差框身份 {frame.frame_id[:8]} 重复；已重新分配身份。")
            frame = replace(frame, frame_id=identity)
        used_annotation_ids.add(frame.frame_id)
        lost_association = False
        restored_rows: list[ToleranceRow] = []
        for row in frame.rows:
            references: list[DatumReference] = []
            for ref in row.datums:
                if ref.datum_id is not None:
                    datum = imported_datums.get(ref.datum_id)
                    if datum is None or datum.label != ref.label:
                        ref = replace(ref, datum_id=None)
                        lost_association = True
                references.append(ref)
            restored_rows.append(replace(row, datums=tuple(references)))
        if lost_association:
            warnings.append(f"形位公差 {frame.frame_id[:8]} 的部分基准关联在导入后需重建")
        elif any(ref.datum_id is None for row in restored_rows for ref in row.datums):
            warnings.append(f"形位公差 {frame.frame_id[:8]} 含未关联的基准引用，请在编辑器中检查。")
        restored_frames.append(replace(frame, rows=tuple(restored_rows)))
    tolerance_frames = restored_frames

    def resolve_annotation(
        attachment: AnnotationAttachment,
    ) -> tuple[AnnotationAttachment, tuple[float, float]] | None:
        x, y = (value * scale for value in attachment.offset_mm)
        if attachment.kind == "frame":
            candidates = [
                current
                for source, current in zip(original_frames, tolerance_frames, strict=True)
                if source.frame_id == attachment.object_id
            ]
            if len(candidates) != 1:
                return None
            target = candidates[0]
            angle = math.radians(target.rotation_deg)
            point = (
                target.position_mm[0] + x * math.cos(angle) - y * math.sin(angle),
                target.position_mm[1] + x * math.sin(angle) + y * math.cos(angle),
            )
            return replace(attachment, object_id=target.frame_id, offset_mm=(x, y)), point
        if attachment.kind == "reference_dimension":
            dimensions = [
                current
                for source, current in zip(original_dimensions, detached_dimensions, strict=True)
                if source.dimension_id == attachment.object_id
            ]
            if len(dimensions) != 1:
                return None
            dimension = dimensions[0]
            return replace(attachment, object_id=dimension.dimension_id, offset_mm=(x, y)), (
                dimension.location_mm[0] + x,
                dimension.location_mm[1] + y,
            )
        if attachment.kind == "sketch_dimension" and attachment.sketch_id is not None:
            dimension_id = dimension_id_map.get((attachment.sketch_id, attachment.object_id))
            dimension = next(
                (item for item in constraints if item.constraint_id == dimension_id), None
            )
            if dimension is None:
                return None
            anchor = (
                dimension.text_position_mm
                if attachment.anchor == "text" and dimension.text_position_mm is not None
                else dimension.position_mm
            )
            if anchor is None:
                return None
            return replace(
                attachment, object_id=dimension.constraint_id, sketch_id=sketch_id, offset_mm=(x, y)
            ), (anchor[0] + x, anchor[1] + y)
        return None

    for index, frame in enumerate(tolerance_frames):
        attachment = frame.leader_annotation_attachment
        if attachment is None:
            continue
        resolved = resolve_annotation(attachment)
        if resolved is not None:
            mapped, point = resolved
            if (
                frame.leader_target_mm is not None
                and math.dist(point, frame.leader_target_mm) <= 1e-7
            ):
                tolerance_frames[index] = replace(
                    frame,
                    leader_annotation_attachment=mapped,
                )
                continue
        warnings.append(f"形位公差 {frame.frame_id[:8]} 的标注附着目标无法恢复，已解除关联。")
        tolerance_frames[index] = replace(frame, leader_annotation_attachment=None)
    frame_by_id = {frame.frame_id: frame for frame in tolerance_frames}
    cyclic_ids: set[str] = set()
    for frame in tolerance_frames:
        path_ids: list[str] = []
        current = frame
        while current.leader_annotation_attachment is not None:
            if current.leader_annotation_attachment.kind != "frame":
                break
            if current.frame_id in path_ids:
                cyclic_ids.update(path_ids[path_ids.index(current.frame_id) :])
                break
            path_ids.append(current.frame_id)
            next_frame = frame_by_id.get(current.leader_annotation_attachment.object_id)
            if next_frame is None:
                break
            current = next_frame
    if cyclic_ids:
        warnings.append("公差框标注附着存在循环，已解除循环中的关联。")
        tolerance_frames = [
            replace(frame, leader_annotation_attachment=None)
            if frame.frame_id in cyclic_ids
            else frame
            for frame in tolerance_frames
        ]
    for index, datum in enumerate(datum_identifiers):
        attachment = datum.annotation_attachment
        if attachment is None:
            continue
        resolved = resolve_annotation(attachment)
        if resolved is None:
            warnings.append(f"基准 {datum.label} 的标注附着目标无法恢复，已解除关联。")
            datum_identifiers[index] = replace(datum, annotation_attachment=None)
            continue
        mapped, point = resolved
        if math.dist(point, datum.target_mm) > 1e-7:
            warnings.append(f"基准 {datum.label} 的标注附着目标无法恢复，已解除关联。")
            datum_identifiers[index] = replace(datum, annotation_attachment=None)
            continue
        datum_identifiers[index] = replace(
            datum,
            annotation_attachment=mapped,
        )
    block_definitions, block_instances, block_handles, text_styles, block_warnings = (
        _read_drawing_blocks(
            document,
            tuple(pending_inserts),
            scale,
            layers,
            known_layer_names,
            text_styles,
            include_nested_referenced=include_nested_referenced_blocks,
        )
    )
    warnings.extend(block_warnings)
    if (
        not entities
        and not texts
        and not tolerance_frames
        and not datum_identifiers
        and not detached_dimensions
        and not block_instances
        and not block_definitions
    ):
        warnings.append("文件中没有可导入的受支持二维图元")
    object_map = DxfObjectMap()
    retained_geometry = {item.entity_id for item in sketch.entities}
    for identity, handle in geometry_handles:
        if identity in retained_geometry:
            object_map.register(DrawingObjectRef("geometry", identity, sketch.sketch_id), (handle,))
    retained_text = {item.text_id for item in texts}
    for identity, handle in text_handles.items():
        if identity in retained_text:
            object_map.register(DrawingObjectRef("text", identity), (handle,))
    for identity, handle in block_handles.items():
        object_map.register(DrawingObjectRef("block_instance", identity), (handle,))
    for identity, handle in associated_handles:
        object_map.register(DrawingObjectRef("dimension", identity, sketch.sketch_id), (handle,))
    for dimension, handle in zip(detached_dimensions, detached_handles, strict=True):
        object_map.register(
            DrawingObjectRef("reference_dimension", dimension.dimension_id), (handle,)
        )
    datum_handle_records: dict[str, list[str]] = {}
    for datum, native in pending_datums:
        datum_handle_records.setdefault(datum.datum_id, []).append(native.dxf.handle)

    def annotation_components(owner: str, identity: str) -> tuple[str, ...] | None:
        key = (owner, identity)
        if key in surface_indications and key not in verified_indications:
            return None
        if key in surface_extensions and key not in restored_surface_extensions:
            return None
        return tuple(
            item.dxf.handle
            for matches in surface_indications.get(key, {}).values()
            for item in matches
        ) + tuple(item.dxf.handle for item in surface_extensions.get(key, ()))

    for datum in datum_identifiers:
        records = datum_handle_records.get(datum.datum_id, [])
        components = annotation_components("datum", datum.datum_id)
        if len(records) == 1 and components is not None:
            object_map.register(DrawingObjectRef("datum", datum.datum_id), (*records, *components))
    for frame in tolerance_frames:
        records = frame_handle_records.get(frame.frame_id, [])
        components = annotation_components("frame", frame.frame_id)
        if len(records) != 1 or components is None:
            continue
        native_handle, leaders = records[0]
        candidates = {
            item.dxf.handle
            for item in (
                *frame_leaders.get(frame.frame_id, ()),
                *native_frame_leaders.get(native_handle, ()),
            )
        }
        if not candidates.issubset(set(leaders)):
            continue
        object_map.register(
            DrawingObjectRef("tolerance", frame.frame_id), (native_handle, *leaders, *components)
        )
    groups, group_warnings = read_native_groups(document, object_map)
    warnings.extend(group_warnings)
    report = DxfExchangeReport(
        "导入",
        document.dxfversion,
        unit_name,
        len(entities)
        + len(constraints)
        + len(texts)
        + len(tolerance_frames)
        + len(datum_identifiers)
        + len(detached_dimensions)
        + len(block_instances),
        tuple(warnings),
    )
    return DxfSketchImport(
        sketch,
        report,
        tuple(imported_styles),
        texts,
        text_styles,
        tuple(tolerance_frames),
        tuple(datum_identifiers),
        tuple(detached_dimensions),
        groups,
        block_definitions,
        block_instances,
    )


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
    ellipse_start: str = "",
    *,
    strict_block: bool = False,
    block_plane_z: float = 0.0,
) -> SketchEntity | None:
    kind = entity.dxftype()
    if kind == "POINT":
        return PointEntity(
            entity_id,
            _xy(entity.dxf.location, scale, strict=strict_block, plane_z=block_plane_z),
            construction,
            layer_name,
        )
    if kind == "ELLIPSE":
        if not (
            _is_exact_xy_normal(entity.dxf.extrusion)
            if strict_block
            else _is_world_xy_normal(entity.dxf.extrusion)
        ):
            raise ValueError("只支持全局 XY 平面的正向椭圆法向。")
        center = _xy(entity.dxf.center, scale, strict=strict_block, plane_z=block_plane_z)
        axis = _xy(entity.dxf.major_axis, scale, strict=strict_block)
        return ellipse_from_dxf(
            entity_id,
            (*center, 0.0),
            (*axis, 0.0),
            entity.dxf.ratio,
            entity.dxf.start_param,
            entity.dxf.end_param,
            clockwise=sweep_sign == "cw",
            full_start_deg=float(ellipse_start) if ellipse_start else None,
            construction=construction,
            layer_name=layer_name,
            strict_sweep=strict_block,
        )
    if kind in {"LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC"} and not (
        _is_exact_xy_normal(entity.dxf.extrusion)
        if strict_block
        else _is_world_xy_normal(entity.dxf.extrusion)
    ):
        raise ValueError("只支持位于全局 XY 平面的图元")
    if kind == "SPLINE":
        spline = cast("_Spline", entity)
        if spline.dxf.get("degree") != 3 or int(cast("int", spline.dxf.get("flags", 0))) & 3:
            raise ValueError("当前支持开放夹持三次均匀 B 样条；周期或闭合样条未导入。")
        if len(spline.weights) not in (0, len(spline.control_points)):
            raise ValueError("样条权重数量与控制点不一致。")
        weights = tuple(spline.weights)
        if strict_block:
            invalid_weights = bool(weights) and (
                not math.isfinite(weights[0])
                or weights[0] <= 0
                or any(weight != weights[0] for weight in weights)
            )
        else:
            invalid_weights = any(
                not math.isfinite(weight) or abs(weight - 1.0) > 1e-12 for weight in weights
            )
        if invalid_weights:
            raise ValueError(
                "当前不支持非正或非等权重的有理样条。"
                if strict_block
                else "当前不支持非单位权重的有理样条。"
            )
        result = SplineEntity(
            entity_id,
            tuple(
                _xy(point, scale, strict=strict_block, plane_z=block_plane_z)
                for point in spline.control_points
            ),
            construction,
            layer_name,
        )
        knots = tuple(float(value) for value in spline.knots)
        if len(knots) != len(result.knots) or knots[-1] <= knots[0]:
            raise ValueError("样条节点向量无效。")
        normalized = tuple((value - knots[0]) / (knots[-1] - knots[0]) for value in knots)
        if any(
            not math.isfinite(value)
            or (value != expected if strict_block else abs(value - expected) > 1e-9)
            for value, expected in zip(normalized, result.knots, strict=True)
        ):
            raise ValueError("当前不支持非均匀或非夹持样条节点；曲线未离散降级。")
        return result
    if kind == "LINE":
        start = _xy(entity.dxf.start, scale, strict=strict_block, plane_z=block_plane_z)
        end = _xy(entity.dxf.end, scale, strict=strict_block, plane_z=block_plane_z)
        return LineEntity(entity_id, start, end, construction, layer_name)
    if kind == "POLYLINE":
        polyline = cast("_LegacyPolyline", entity)
        if polyline.dxf.get("invisible", 0) or polyline.dxf.get("thickness", 0):
            raise ValueError("不支持隐藏或具有三维厚度的传统多段线")
        flags = int(cast("int", polyline.dxf.get("flags", 0)))
        if not polyline.is_2d_polyline or flags & ~1:
            raise ValueError("只支持未拟合的二维传统多段线")
        if polyline.dxf.get("default_start_width", 0) or polyline.dxf.get("default_end_width", 0):
            raise ValueError("当前不支持具有宽度的多段线")
        _x, _y, elevation = _xyz(polyline.dxf.get("elevation", (0, 0, 0)))
        if (strict_block and elevation != block_plane_z) or (
            not strict_block and abs(elevation) > 1e-7
        ):
            raise ValueError("传统多段线不在块成员平面")
        legacy_points: list[tuple[float, float]] = []
        legacy_bulges: list[float] = []
        for vertex in polyline.vertices:
            if vertex.dxf.get("flags", 0):
                raise ValueError("不支持曲线拟合或三维多段线顶点")
            if vertex.dxf.get("start_width", 0) or vertex.dxf.get("end_width", 0):
                raise ValueError("当前不支持具有宽度的多段线")
            vertex_x, vertex_y, vertex_z = _xyz(vertex.dxf.location)
            if vertex_z not in (0.0, elevation):
                raise ValueError("传统多段线顶点高度与多段线高度不一致")
            legacy_points.append((vertex_x * scale, vertex_y * scale))
            legacy_bulges.append(float(cast("float", vertex.dxf.get("bulge", 0.0))))
        if len(legacy_points) < 2:
            raise ValueError("多段线至少需要两个顶点")
        if not polyline.is_closed and legacy_bulges[-1] != 0:
            raise ValueError("开放多段线末尾的未使用 bulge 无法保留")
        return PolylineEntity(
            entity_id,
            tuple(legacy_points),
            polyline.is_closed,
            construction,
            layer_name,
            tuple(legacy_bulges if polyline.is_closed else legacy_bulges[:-1]),
        )
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
        if (
            isinstance(z, bool)
            or not isinstance(z, int | float)
            or not math.isfinite(z)
            or (float(z) != block_plane_z if strict_block else abs(float(z)) > 1e-7)
        ):
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
        center = _xy(entity.dxf.center, scale, strict=strict_block, plane_z=block_plane_z)
        return CircleEntity(
            entity_id, center, float(entity.dxf.radius) * scale, construction, layer_name
        )
    if kind == "ARC":
        center = _xy(entity.dxf.center, scale, strict=strict_block, plane_z=block_plane_z)
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


def _xyz(value: object) -> tuple[float, float, float]:
    try:
        x, y, z = cast("Sequence[float]", value)
    except (TypeError, ValueError) as exc:
        raise ValueError("图元坐标格式无效") from exc
    if not all(math.isfinite(component) for component in (x, y, z)):
        raise ValueError("图元坐标必须有限")
    return float(x), float(y), float(z)


def _xy(
    value: object, scale: float, *, strict: bool = False, plane_z: float = 0.0
) -> tuple[float, float]:
    x, y, z = _xyz(value)
    if z != plane_z if strict else abs(z) > 1e-7:
        raise ValueError("只支持位于 DXF XY 平面的图元")
    return (x * scale, y * scale)


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


def _is_exact_xy_normal(value: object) -> bool:
    """Reject tilted block planes instead of silently flattening large geometry."""
    return is_exact_positive_xy_normal(value)


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
