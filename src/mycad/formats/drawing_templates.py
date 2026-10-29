# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF template exchange and an atomic, portable JSON template library."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Literal, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

import ezdxf.filemanagement as filemanagement
from ezdxf.document import Drawing
from ezdxf.entities.arc import Arc
from ezdxf.entities.attrib import AttDef, Attrib
from ezdxf.entities.circle import Circle
from ezdxf.entities.dxfentity import DXFEntity
from ezdxf.entities.insert import Insert
from ezdxf.entities.line import Line
from ezdxf.entities.lwpolyline import LWPolyline
from ezdxf.entities.mtext import MText
from ezdxf.entities.polyline import Polyline
from ezdxf.entities.text import Text
from ezdxf.entities.viewport import Viewport
from ezdxf.lldxf.const import DXFError
from ezdxf.math import Vec3

from mycad.core.drawing_projection import ArcCurve, LineCurve, Point2
from mycad.core.drawing_templates import DrawingTemplate, TemplateCurve, TemplateText

UNIT_FACTORS = {"mm": 1.0, "inch": 25.4, "cm": 10.0, "m": 1000.0}
_DXF_UNITS = {1: "inch", 4: "mm", 5: "cm", 6: "m"}
_MAX_BYTES = 16 * 1024 * 1024


def _read(path: Path) -> Drawing:
    if path.stat().st_size > _MAX_BYTES:
        raise ValueError("模板文件不能超过 16 MiB")
    try:
        return cast("Callable[[Path], Drawing]", vars(filemanagement)["readfile"])(path)
    except (DXFError, OSError, UnicodeError) as error:
        raise ValueError(f"无法读取 DXF：{error}") from error


def dxf_layouts(path: Path) -> tuple[str, ...]:
    return tuple(_read(path).layouts.names())


def _expand(entities: Iterable[DXFEntity], depth: int = 0) -> Iterable[DXFEntity]:
    if depth > 16:
        raise ValueError("模板图块嵌套超过 16 层或存在循环")
    for entity in entities:
        if isinstance(entity, Insert):
            block = entity.block()
            if (
                block is None
                or block.block is None
                or block.block.is_xref
                or entity.has_extension_dict
            ):
                raise ValueError("模板不支持缺失图块、外部参照或带裁剪/扩展数据的 INSERT")
            if entity.mcount > 1:
                raise ValueError("模板不支持阵列 INSERT，请先分解")
            yield from entity.attribs
            for definition in block.attdefs():
                if definition.is_const and not entity.has_attrib(definition.dxf.tag):
                    yield definition.copy().transform(entity.matrix44())

            def skipped(skipped_entity: DXFEntity, reason: str) -> None:
                raise ValueError(f"模板图块无法展开 {skipped_entity.dxftype()}：{reason}")

            yield from _expand(entity.virtual_entities(skipped_entity_callback=skipped), depth + 1)
        elif isinstance(entity, LWPolyline | Polyline):
            if isinstance(entity, Polyline) and not entity.is_2d_polyline:
                raise ValueError("模板只接受二维多段线")
            if entity.has_width:
                raise ValueError("模板不支持有宽度的多段线，请先转成轮廓")
            yield from entity.virtual_entities()
        elif isinstance(entity, AttDef):
            # ATTDEF belongs to a block definition; instantiated ATTRIB carries the value.
            if entity.is_const:
                yield entity
        elif isinstance(entity, Viewport) and entity.dxf.id == 1:
            continue  # Layout's paper background viewport has no drawing content.
        else:
            yield entity


def import_dxf_template(
    path: Path,
    *,
    name: str,
    size_mm: Point2,
    layout: str = "Model",
    unit: str | None = None,
    offset_mm: Point2 = (0, 0),
) -> DrawingTemplate:
    document = _read(path)
    unit = unit or _DXF_UNITS.get(document.units)
    if unit not in UNIT_FACTORS:
        raise ValueError("DXF 单位未知或不支持，请明确选择源文件单位")
    factor = UNIT_FACTORS[unit]
    if layout not in document.layouts:
        raise ValueError(f"DXF 布局不存在：{layout}")
    curves: list[TemplateCurve] = []
    texts: list[TemplateText] = []

    def xy(value: Vec3) -> Point2:
        if abs(value.z) > 1e-7:
            raise ValueError("模板只接受 XY 平面图元")
        return value.x * factor + offset_mm[0], value.y * factor + offset_mm[1]

    for entity in _expand(document.layouts.get(layout)):
        if len(curves) + len(texts) >= 20000:
            raise ValueError("模板超过 20000 个图元")
        if isinstance(entity, Line):
            curves.append(LineCurve(xy(entity.dxf.start), xy(entity.dxf.end)))
        elif isinstance(entity, Circle):
            if not entity.dxf.extrusion.isclose(Vec3(0, 0, 1)):
                raise ValueError("模板圆弧不在全局 XY 平面")
            start = entity.dxf.start_angle if isinstance(entity, Arc) else 0.0
            sweep = (
                (entity.dxf.end_angle - start) % 360 or 360 if isinstance(entity, Arc) else 360.0
            )
            curves.append(ArcCurve(xy(entity.dxf.center), entity.dxf.radius * factor, start, sweep))
        elif isinstance(entity, Text | MText):
            texts.append(_text(entity, factor, offset_mm))
        else:
            raise ValueError(f"模板不支持 {entity.dxftype()}，请在源 CAD 中转换后再导入")
    template = DrawingTemplate(
        str(uuid4()), name, "自定义 / 导入 DXF", size_mm, tuple(curves), tuple(texts)
    )
    # Only explicit translation/unit conversion is allowed; never silently fit or distort.
    for curve in curves:
        points = (
            (curve.start, curve.end)
            if isinstance(curve, LineCurve)
            else tuple(
                (
                    curve.center[0]
                    + curve.radius
                    * math.cos(math.radians(curve.start_deg + curve.sweep_deg * i / 360)),
                    curve.center[1]
                    + curve.radius
                    * math.sin(math.radians(curve.start_deg + curve.sweep_deg * i / 360)),
                )
                for i in range(361)
            )
        )
        if any(
            not -0.01 <= p[0] <= size_mm[0] + 0.01 or not -0.01 <= p[1] <= size_mm[1] + 0.01
            for p in points
        ):
            raise ValueError("模板图元超出所选幅面，请检查单位、幅面与原点偏移")
    if any(
        not 0 <= t.position_mm[0] <= size_mm[0] or not 0 <= t.position_mm[1] <= size_mm[1]
        for t in texts
    ):
        raise ValueError("模板文字位置超出所选幅面，请检查单位或原点偏移")
    return template


def _text(entity: Text | MText, factor: float, offset: Point2) -> TemplateText:
    if not entity.dxf.extrusion.isclose(Vec3(0, 0, 1)):
        raise ValueError("模板文字不在全局 XY 平面")
    align: Literal["left", "center", "right"] = "left"
    if isinstance(entity, MText):
        value = cast("str", entity.plain_text())
        height = float(entity.dxf.char_height)
        pos = Vec3(entity.dxf.insert)
        rotation = entity.get_rotation()
        attachment = int(entity.dxf.attachment_point)
        if attachment not in (1, 2, 3) or entity.has_columns:
            raise ValueError("MTEXT 目前支持顶端对齐、无分栏文字，请转换后再导入")
        align = ("left", "center", "right")[attachment - 1]
        # Wrapped/formatted MTEXT would otherwise lose its layout silently.
        raw = entity.text.replace("\\P", "\n").replace("\\~", " ")
        if raw != value:
            raise ValueError("MTEXT 含内嵌格式，请转为普通文字后导入")
        width = float(entity.dxf.width)
        if width and any(
            sum(1.5 if ord(c) > 255 else 1.1 for c in line) * height > width
            for line in value.split("\n")
        ):
            raise ValueError("MTEXT 自动换行不能保留，请改为显式换行后导入")
    else:
        value = entity.plain_text()
        placement, pos, _ = entity.get_placement()
        if placement.name not in ("LEFT", "CENTER", "RIGHT", "TOP_LEFT", "TOP_CENTER", "TOP_RIGHT"):
            raise ValueError(f"TEXT 对齐方式 {placement.name} 尚不支持，请改为左/中/右对齐")
        if (
            entity.dxf.text_generation_flag
            or entity.dxf.oblique
            or abs(entity.dxf.width - 1) > 1e-7
        ):
            raise ValueError("模板不支持镜像、倾斜或拉伸文字")
        height, rotation = float(entity.dxf.height), float(entity.dxf.rotation)
        align = (
            "center"
            if "CENTER" in placement.name
            else "right"
            if "RIGHT" in placement.name
            else "left"
        )
        if not placement.name.startswith("TOP_"):
            # TEXT insertion is a baseline; our paper text anchor is the cap top.
            angle = math.radians(rotation)
            pos += Vec3(-math.sin(angle) * height, math.cos(angle) * height, 0)
    if abs(pos.z) > 1e-7:
        raise ValueError("模板文字只接受 XY 平面")
    field = str(entity.dxf.tag) if isinstance(entity, Attrib | AttDef) else ""
    if not field and value.startswith("{{") and value.endswith("}}"):
        field, value = value[2:-2].strip(), ""
    return TemplateText(
        (pos.x * factor + offset[0], pos.y * factor + offset[1]),
        value,
        height * factor,
        field,
        rotation_deg=rotation,
        align=align,
    )


class TemplateLibrary:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def load(self) -> tuple[tuple[DrawingTemplate, ...], tuple[str, ...]]:
        templates: list[DrawingTemplate] = []
        issues: list[str] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                if path.stat().st_size > _MAX_BYTES:
                    raise ValueError("模板文件超过 16 MiB")
                template = DrawingTemplate.from_mapping(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                if any(t.template_id == template.template_id for t in templates):
                    raise ValueError("模板 ID 重复")
                templates.append(template)
            except (OSError, ValueError, RecursionError) as error:
                issues.append(f"{path.name}：{error}")
        return tuple(templates), tuple(issues)

    def save(self, template: DrawingTemplate) -> Path:
        payload = json.dumps(template.to_mapping(), ensure_ascii=False, allow_nan=False, indent=2)
        if len(payload.encode("utf-8")) > _MAX_BYTES:
            raise ValueError("模板文件超过 16 MiB")
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{uuid5(NAMESPACE_URL, template.template_id)}.json"
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=self.directory, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target
