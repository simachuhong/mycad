# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Portable, versioned paper templates. No external files are needed for replay."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal, cast

from mycad.core.drawing_projection import ArcCurve, LineCurve, Point2, finite

PAPER_SIZES: dict[str, Point2] = {
    "A4": (210, 297),
    "A3": (297, 420),
    "A2": (420, 594),
    "A1": (594, 841),
    "A0": (841, 1189),
}
TemplateCurve = LineCurve | ArcCurve


def record(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(
        not isinstance(k, str) for k in cast("dict[object, object]", value)
    ):
        raise ValueError("模板对象必须为 JSON object")
    return cast("dict[str, object]", value)


def items(value: object) -> list[object]:
    if not isinstance(value, list | tuple):
        raise ValueError("模板数组无效")
    return list(cast("list[object]", value))


def number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("模板数值无效")
    finite((value,), "template")
    return float(value)


def text(value: object) -> str:
    if not isinstance(value, str) or len(value) > 10000:
        raise ValueError("模板文字无效或超过 10000 字符")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError("模板文字含控制字符")
    return value


def point(value: object) -> Point2:
    values = items(value)
    if len(values) != 2:
        raise ValueError("模板坐标需要两个数值")
    return number(values[0]), number(values[1])


@dataclass(frozen=True, slots=True)
class TemplateText:
    position_mm: Point2
    text: str
    height_mm: float = 2.5
    field: str = ""
    width_mm: float = 0
    rotation_deg: float = 0
    align: Literal["left", "center", "right"] = "left"

    def __post_init__(self) -> None:
        finite(
            (*self.position_mm, self.height_mm, self.width_mm, self.rotation_deg), "template text"
        )
        text(self.text)
        text(self.field)
        if not 0 < self.height_mm <= 100 or self.width_mm < 0:
            raise ValueError("模板文字尺寸无效")
        if self.align not in ("left", "center", "right"):
            raise ValueError("模板文字对齐无效")

    def value(self, fields: Mapping[str, str]) -> str:
        return fields.get(self.field, self.text) if self.field else self.text


def _read_text(value: object) -> TemplateText:
    obj = record(value)
    if set(obj) != {
        "position_mm",
        "text",
        "height_mm",
        "field",
        "width_mm",
        "rotation_deg",
        "align",
    }:
        raise ValueError("模板文字字段无效")
    return TemplateText(
        point(obj["position_mm"]),
        text(obj["text"]),
        number(obj["height_mm"]),
        text(obj["field"]),
        number(obj["width_mm"]),
        number(obj["rotation_deg"]),
        cast('Literal["left", "center", "right"]', text(obj["align"])),
    )


@dataclass(frozen=True, slots=True)
class DrawingTemplate:
    template_id: str
    name: str
    standard: str
    size_mm: Point2
    curves: tuple[TemplateCurve, ...]
    texts: tuple[TemplateText, ...]

    def __post_init__(self) -> None:
        for value in (self.template_id, self.name, self.standard):
            if not text(value).strip():
                raise ValueError("模板标识、名称和标准不能为空")
        finite(self.size_mm, "template size")
        if not 10 <= min(self.size_mm) <= max(self.size_mm) <= 10000:
            raise ValueError("模板幅面必须为 10–10000 mm")
        if not self.curves or len(self.curves) + len(self.texts) > 20000:
            raise ValueError("模板图元为空或超过 20000 个")

    def to_mapping(self) -> dict[str, object]:
        return {
            "format": "mycad.drawing-template",
            "version": 1,
            "template_id": self.template_id,
            "name": self.name,
            "standard": self.standard,
            "size_mm": list(self.size_mm),
            "curves": [
                {"kind": "line" if isinstance(c, LineCurve) else "arc", **asdict(c)}
                for c in self.curves
            ],
            "texts": [asdict(t) for t in self.texts],
        }

    @classmethod
    def from_mapping(cls, value: object) -> DrawingTemplate:
        obj = record(value)
        if set(obj) != {
            "format",
            "version",
            "template_id",
            "name",
            "standard",
            "size_mm",
            "curves",
            "texts",
        }:
            raise ValueError("模板字段无效")
        if (
            obj["format"] != "mycad.drawing-template"
            or type(obj["version"]) is not int
            or obj["version"] != 1
        ):
            raise ValueError("不支持的模板格式或版本")
        raw_curves, raw_texts = items(obj["curves"]), items(obj["texts"])
        if len(raw_curves) + len(raw_texts) > 20000:
            raise ValueError("模板超过 20000 个图元")
        curves: list[TemplateCurve] = []
        for raw in raw_curves:
            c = record(raw)
            if c.get("kind") == "line" and set(c) == {"kind", "start", "end"}:
                curves.append(LineCurve(point(c["start"]), point(c["end"])))
            elif c.get("kind") == "arc" and set(c) == {
                "kind",
                "center",
                "radius",
                "start_deg",
                "sweep_deg",
            }:
                curves.append(
                    ArcCurve(
                        point(c["center"]),
                        number(c["radius"]),
                        number(c["start_deg"]),
                        number(c["sweep_deg"]),
                    )
                )
            else:
                raise ValueError("不支持的模板曲线")
        return cls(
            text(obj["template_id"]),
            text(obj["name"]),
            text(obj["standard"]),
            point(obj["size_mm"]),
            tuple(curves),
            tuple(_read_text(t) for t in raw_texts),
        )


def rectangle(x: float, y: float, width: float, height: float) -> tuple[LineCurve, ...]:
    points = ((x, y), (x + width, y), (x + width, y + height), (x, y + height))
    return tuple(LineCurve(a, b) for a, b in zip(points, (*points[1:], points[0]), strict=True))


def builtin_template(
    standard: str, paper: str, *, landscape: bool = True, projection_angle: str = "first"
) -> DrawingTemplate:
    if standard not in ("GB", "ISO") or paper not in PAPER_SIZES:
        raise ValueError("模板标准/幅面无效")
    if projection_angle not in ("first", "third"):
        raise ValueError("模板投影法无效")
    short, long = PAPER_SIZES[paper]
    width, height = (long, short) if landscape else (short, long)
    margin = (5 if paper in ("A3", "A4") else 10) if standard == "GB" else 10
    left = 25 if standard == "GB" else 20
    curves: list[TemplateCurve] = list(
        rectangle(left, margin, width - left - margin, height - 2 * margin)
    )
    # Common mechanical title-block layout; ISO 7200 specifies fields, not a unique grid.
    x, y = width - margin - 180, margin
    curves.extend(rectangle(x, y, 180, 56))
    for dy in (14, 28, 42):
        curves.append(LineCurve((x, y + dy), (x + 180, y + dy)))
    for dx in (45, 90, 135):
        curves.append(LineCurve((x + dx, y), (x + dx, y + 28)))
    curves.append(LineCurve((x + 90, y + 28), (x + 90, y + 56)))
    labels: list[TemplateText] = []
    fields = [
        ("单位", "Owner", 0, 42, 90),
        ("标题", "Title", 90, 42, 90),
        ("图号", "Drawing No.", 0, 28, 90),
        ("材料", "Material", 90, 28, 90),
        ("设计", "Drawn by", 0, 14, 45),
        ("审核", "Approved by", 45, 14, 45),
        ("日期", "Date", 90, 14, 45),
        ("版本", "Revision", 135, 14, 45),
        ("比例", "Scale", 0, 0, 45),
        ("页码", "Sheet", 45, 0, 45),
        ("质量", "Mass", 90, 0, 45),
    ]
    for key, en, dx, dy, cell_width in fields:
        labels.append(TemplateText((x + dx + 2, y + dy + 12), key if standard == "GB" else en, 2.2))
        labels.append(TemplateText((x + dx + 2, y + dy + 7), "", 3, key, cell_width - 4))
    # Frustum side view plus circular end view; first/third swaps the circle's side.
    fx, fy = x + 146, y + 4
    if projection_angle == "third":
        fx += 17
    curves.extend(
        (
            LineCurve((fx, fy), (fx + 10, fy + 2)),
            LineCurve((fx + 10, fy + 2), (fx + 10, fy + 6)),
            LineCurve((fx + 10, fy + 6), (fx, fy + 8)),
            LineCurve((fx, fy + 8), (fx, fy)),
        )
    )
    cx = fx + 17 if projection_angle == "first" else fx - 7
    curves.extend((ArcCurve((cx, fy + 4), 4), ArcCurve((cx, fy + 4), 2)))
    references = (
        "GB/T 14689-2008; GB/T 10609.1-2008"
        if standard == "GB"
        else "ISO 5457:1999+A1:2010; ISO 7200:2004"
    )
    return DrawingTemplate(
        f"builtin:{standard}:{paper}:{'L' if landscape else 'P'}:{projection_angle}:1",
        f"{standard} {paper} {'横向' if landscape else '纵向'}",
        references,
        (width, height),
        tuple(curves),
        tuple(labels),
    )
