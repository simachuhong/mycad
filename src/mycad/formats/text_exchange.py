# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Editable native DXF text and STYLE adapters, independent of the Qt renderer."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Iterator, Mapping, MutableMapping, Sequence
from dataclasses import replace
from typing import Protocol, cast
from uuid import uuid4

from ezdxf.lldxf.const import DXFTableEntryError
from ezdxf.lldxf.encoding import decode_dxf_unicode

from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
from mycad.core.exceptions import ValidationError
from mycad.formats.dxf_collections import is_exact_positive_xy_normal, unique_import_name


class _Attributes(Protocol):
    def get(self, name: str, default: object = None) -> object: ...


class _Entity(Protocol):
    dxf: _Attributes
    text: str
    has_columns: bool

    def dxftype(self) -> str: ...
    def plain_text(self) -> str: ...
    def get_rotation(self) -> float: ...


class _Style(Protocol):
    dxf: _Attributes

    def get_extended_font_data(self) -> tuple[str, bool, bool]: ...
    def set_extended_font_data(
        self, family: str = "", *, italic: bool = False, bold: bool = False
    ) -> None: ...


class _Styles(Protocol):
    def __contains__(self, name: str) -> bool: ...
    def get(self, name: str) -> _Style: ...
    def new(self, name: str, *, dxfattribs: Mapping[str, object]) -> _Style: ...


class _Layers(Protocol):
    def __contains__(self, name: str) -> bool: ...
    def new(self, name: str, *, dxfattribs: Mapping[str, object]) -> object: ...


class _Space(Protocol):
    def __iter__(self) -> Iterator[_Entity]: ...
    def add_text(self, text: str, *, dxfattribs: Mapping[str, object]) -> _Entity: ...
    def add_mtext(self, text: str, *, dxfattribs: Mapping[str, object]) -> _Entity: ...


class _Document(Protocol):
    styles: _Styles
    layers: _Layers

    def modelspace(self) -> _Space: ...


_HORIZONTAL = {"left": 0, "center": 1, "right": 2}
_VERTICAL = {"bottom": 1, "middle": 2, "top": 3}
_ATTACHMENTS = (
    "top_left",
    "top_center",
    "top_right",
    "middle_left",
    "middle_center",
    "middle_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
)
_WIDTH_PREFIX = re.compile(r"^\\W([0-9.+eE-]+);")


def _unwrap_mtext_group(content: str) -> str:
    """Unwrap only groups covering the entire content, preserving partial scopes."""
    while content.startswith("{") and content.endswith("}"):
        depth = 0
        escaped = False
        for index, char in enumerate(content):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0 and index != len(content) - 1:
                    return content
                if depth < 0:
                    return content
        if depth:
            return content
        content = content[1:-1]
    return content


def _number(attributes: _Attributes, name: str, default: float) -> float:
    raw = attributes.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
        raise ValueError(f"invalid DXF text {name}")
    return float(raw)


def _position(
    attributes: _Attributes, name: str, scale: float, *, strict: bool = False, plane_z: float = 0.0
) -> tuple[float, float]:
    point = tuple(cast("Sequence[float]", attributes.get(name, (0.0, 0.0, 0.0))))
    if (
        len(point) < 2
        or not all(math.isfinite(value) for value in point[:3])
        or (
            (point[2] if len(point) > 2 else 0.0) != plane_z
            if strict
            else len(point) > 2 and abs(point[2]) > 1e-9
        )
    ):
        raise ValueError("文字位置不在 XY 平面")
    return point[0] * scale, point[1] * scale


def _escape_mtext(content: str) -> str:
    value = content.replace("^", "^ ").replace("\\", "\\\\")
    value = value.replace("{", r"\{").replace("}", r"\}")
    value = re.sub(r"%(?=%)", "%{}", value)
    return value.replace("\n", r"\P")


def _escape_text(content: str) -> str:
    # %%nnn is the native TEXT ASCII escape; encoding each percent prevents
    # literal user strings such as %%d from becoming a diameter symbol.
    return content.replace("\\", r"\U+005C").replace("^", "^ ").replace("%", "%%037")


def _plain_text(entity: _Entity) -> str:
    raw = str(entity.dxf.get("text", ""))
    # Decode numeric TEXT escapes after the ordinary DXF special-character pass
    # so a decoded literal percent cannot start another formatting instruction.
    result = decode_dxf_unicode(entity.plain_text())
    return re.sub(r"%%(\d{3})", lambda match: chr(int(match[1])), result) if raw else result


def _native_style_name(name: str, identity: str, styles: _Styles) -> str:
    """Fit the native name to the DXF string limit without splitting UTF-8."""
    if len(name.encode("utf-8")) <= 255 and name not in styles:
        return name
    counter = 0
    while True:
        suffix = "_" + hashlib.sha256(f"{identity}\0{counter}".encode()).hexdigest()[:12]
        prefix = name.encode("utf-8")[: 255 - len(suffix)].decode("utf-8", errors="ignore").rstrip()
        candidate = (prefix or "style") + suffix
        if candidate not in styles:
            return candidate
        counter += 1


def write_texts_dxf(
    document: object,
    texts: tuple[DrawingText, ...],
    styles: TextStyleTable | None = None,
    *,
    style_names: dict[str, str] | None = None,
    handle_map: MutableMapping[str, str] | None = None,
    layout: object | None = None,
    reuse_styles: bool = False,
) -> tuple[str, ...]:
    """Write native entities; no custom payload can mask later native edits."""
    target = cast("_Document", document)
    table = styles or TextStyleTable()
    warnings: list[str] = []
    native_names: dict[str, str] = {}
    for style in table.styles:
        if reuse_styles:
            if style_names is None or style.style_id not in style_names:
                raise ValidationError("块文字缺少已导出的 DXF 文字样式。")
            native_names[style.style_id] = style_names[style.style_id]
            continue
        for field, value in (("字体文件", style.font_file), ("字体族", style.font_family)):
            if len(value.encode("utf-8")) > 255:
                raise ValidationError(f"文字样式 {style.name} 的{field}超过 DXF 255 字节限制。")
        name = _native_style_name(
            re.sub(r'[<>/\\":;?*|=,`]', "_", style.name), style.style_id, target.styles
        )
        if name != style.name:
            warnings.append(f"文字样式 {style.name} 的 DXF 名称已转换为 {name}")
        native = target.styles.new(
            name,
            dxfattribs={
                "font": style.font_file,
                "height": style.height_mm,
                "width": style.width_factor,
            },
        )
        if style.font_family:
            native.set_extended_font_data(
                style.font_family,
                italic="italic" in style.font_style.casefold(),
                bold="bold" in style.font_style.casefold(),
            )
        native_names[style.style_id] = name
        if style_names is not None:
            style_names[style.style_id] = name
        if style.font_file.lower().endswith(".shx"):
            warnings.append(f"文字样式 {style.name} 使用 SHX；MyCAD 暂不提供 SHX 绘制")
    modelspace = target.modelspace() if layout is None else cast("_Space", layout)
    for text in texts:
        style = table.get(text.style_id)
        height = text.height_mm if text.height_mm is not None else style.height_mm
        width = text.width_factor if text.width_factor is not None else style.width_factor
        if text.layer_name not in target.layers:
            target.layers.new(text.layer_name, dxfattribs={})
        attributes: dict[str, object] = {
            "layer": text.layer_name,
            "style": native_names[text.style_id],
            "insert": (*text.position_mm, 0.0),
            "rotation": text.rotation_deg,
        }
        if text.kind == "text":
            vertical, horizontal = (
                text.align.split("_", 1) if "_" in text.align else ("", text.align)
            )
            attributes.update(
                {
                    "height": height,
                    "width": width,
                    "halign": _HORIZONTAL[horizontal],
                    "valign": _VERTICAL.get(vertical, 0),
                    "align_point": (*text.position_mm, 0.0),
                }
            )
            entity = modelspace.add_text(_escape_text(text.text), dxfattribs=attributes)
        else:
            alignment = text.align
            if alignment in _HORIZONTAL:
                alignment = f"bottom_{alignment}"
                warnings.append(f"多行文字 {text.text_id[:8]} 的基线对齐已转换为底部对齐")
            attributes.update(
                {
                    "char_height": height,
                    "width": text.box_width_mm,
                    "attachment_point": _ATTACHMENTS.index(alignment) + 1,
                    "line_spacing_factor": min(4.0, max(0.25, text.line_spacing)),
                    "line_spacing_style": 2,
                }
            )
            if not 0.25 <= text.line_spacing <= 4.0:
                warnings.append(f"多行文字 {text.text_id[:8]} 行距超出 DXF 范围，已限制到 0.25–4")
            entity = modelspace.add_mtext(
                f"\\W{width:.15g};{_escape_mtext(text.text)}", dxfattribs=attributes
            )
        if handle_map is not None:
            handle = entity.dxf.get("handle")
            if not isinstance(handle, str) or not handle:
                raise ValidationError("导出文字缺少 DXF handle。")
            handle_map[text.text_id] = handle
    return tuple(warnings)


def _read_style(target: _Document, name: str, scale: float) -> TextStyle:
    native = target.styles.get(name)
    family, italic, bold = native.get_extended_font_data()
    height = _number(native.dxf, "height", 0.0)
    return TextStyle(
        "dxf_" + hashlib.sha256(name.lower().encode()).hexdigest()[:24],
        name,
        family,
        "Bold Italic" if bold and italic else "Bold" if bold else "Italic" if italic else "Regular",
        str(native.dxf.get("font", "")),
        height * scale if height > 0 else 3.5,
        _number(native.dxf, "width", 1.0),
    )


def read_dxf_text_style(document: object, name: str, scale: float) -> TextStyle:
    """Read a named native STYLE referenced by an imported dimension."""
    return _read_style(cast("_Document", document), name, scale)


def native_style_matches_snapshot(current: TextStyle, snapshot: TextStyle) -> bool:
    """Accept the old casefold-derived identity only when all native data matches."""
    if current == snapshot:
        return True
    legacy_id = "dxf_" + hashlib.sha256(current.name.casefold().encode()).hexdigest()[:24]
    return snapshot.style_id == legacy_id and replace(current, style_id=legacy_id) == snapshot


def read_texts_dxf(
    document: object,
    scale: float,
    *,
    entities: Iterable[object] | None = None,
    handle_map: MutableMapping[str, str] | None = None,
    strict_format: bool = False,
    plane_z: float = 0.0,
) -> tuple[tuple[DrawingText, ...], TextStyleTable | None, tuple[str, ...]]:
    """Read native text; strict mode rejects entity formatting that would be lost."""
    target = cast("_Document", document)
    texts: list[DrawingText] = []
    styles: dict[str, TextStyle] = {}
    used_style_names: set[str] = set()
    warnings: list[str] = []

    def report_loss(message: str) -> None:
        if strict_format:
            raise ValueError(message)
        warnings.append(message)

    source = target.modelspace() if entities is None else cast("Iterable[_Entity]", entities)
    for entity in source:
        kind = entity.dxftype()
        if kind not in ("TEXT", "MTEXT"):
            continue
        label = f"{kind} {entity.dxf.get('handle', '')}"
        try:
            extrusion = cast("Sequence[float]", entity.dxf.get("extrusion", (0, 0, 1)))
            if not (
                is_exact_positive_xy_normal(extrusion)
                if strict_format
                else tuple(extrusion) == (0, 0, 1)
            ):
                raise ValueError("文字法向不在支持的 XY 平面")
            name = str(entity.dxf.get("style", "Standard"))
            key = name.lower()
            if strict_format:
                native_style = target.styles.get(name)
                if native_style.dxf.get("oblique", 0) or native_style.dxf.get(
                    "generation_flags", 0
                ):
                    report_loss(f"{label} 使用不支持的倾斜/镜像文字样式")
                if int(_number(native_style.dxf, "flags", 0)) & 4:
                    report_loss(f"{label} 使用不支持的竖排文字样式")
            style = styles.get(key)
            if style is None:
                style = _read_style(target, name, scale)
                unique_name = unique_import_name(style.name, used_style_names, max_length=512)
                if unique_name != style.name:
                    style = replace(style, name=unique_name)
            width_factor = 1.0
            if kind == "TEXT":
                content = _plain_text(entity)
                horizontal = int(_number(entity.dxf, "halign", 0))
                vertical = int(_number(entity.dxf, "valign", 0))
                if horizontal not in (0, 1, 2) or vertical not in (0, 1, 2, 3):
                    raise ValueError("文字使用尚不支持的 FIT/ALIGNED 对齐")
                alignment = ("left", "center", "right")[horizontal]
                if vertical:
                    alignment = f"{('', 'bottom', 'middle', 'top')[vertical]}_{alignment}"
                position = _position(
                    entity.dxf,
                    "align_point" if horizontal or vertical else "insert",
                    scale,
                    strict=strict_format,
                    plane_z=plane_z,
                )
                height = _number(entity.dxf, "height", style.height_mm / scale) * scale
                width_factor = _number(entity.dxf, "width", 1.0)
                box_width, line_spacing = 0.0, 1.0
                rotation = _number(entity.dxf, "rotation", 0.0)
                if entity.dxf.get("oblique", 0) or entity.dxf.get("text_generation_flag", 0):
                    report_loss(f"{label} 的倾斜/镜像文字格式未保留")
            else:
                direction = entity.dxf.get("text_direction")
                if direction is not None:
                    vector = tuple(cast("Sequence[float]", direction))
                    if (
                        len(vector) != 3
                        or not all(math.isfinite(value) for value in vector)
                        or (vector[2] != 0 if strict_format else abs(vector[2]) > 1e-9)
                        or (
                            vector[0] == 0 and vector[1] == 0
                            if strict_format
                            else math.hypot(vector[0], vector[1]) <= 1e-12
                        )
                    ):
                        raise ValueError("多行文字方向不是有效的 XY 平面向量")
                raw = _unwrap_mtext_group(entity.text)
                width = _WIDTH_PREFIX.match(raw)
                checked = raw[width.end() :] if width else raw
                if width:
                    width_factor = float(width[1])
                # Escapes and paragraph breaks are supported. Other inline
                # formatting is flattened by ezdxf and must be disclosed.
                if any(match[0][1] not in "\\{}P" for match in re.finditer(r"\\.", checked)):
                    report_loss(f"{label} 包含不支持的局部文字格式，已转换为统一样式")
                content = entity.plain_text()
                attachment = int(_number(entity.dxf, "attachment_point", 1))
                if not 1 <= attachment <= 9:
                    raise ValueError("invalid MTEXT attachment")
                alignment = _ATTACHMENTS[attachment - 1]
                position = _position(
                    entity.dxf, "insert", scale, strict=strict_format, plane_z=plane_z
                )
                height = _number(entity.dxf, "char_height", 2.5) * scale
                box_width = _number(entity.dxf, "width", 0.0) * scale
                line_spacing = _number(entity.dxf, "line_spacing_factor", 1.0)
                if entity.dxf.get("line_spacing_style", 1) != 2:
                    report_loss(f"{label} 的最小行距模式已按固定行距近似导入")
                rotation = entity.get_rotation()
                if entity.has_columns:
                    report_loss(f"{label} 的多栏格式未保留")
            text = DrawingText(
                str(uuid4()),
                content,
                position,
                kind=kind.lower(),
                style_id=style.style_id,
                height_mm=height,
                width_factor=width_factor,
                rotation_deg=rotation,
                align=alignment,
                box_width_mm=box_width,
                line_spacing=line_spacing,
                layer_name=str(entity.dxf.get("layer", "0")),
            )
            if len(styles) >= 500 and key not in styles:
                raise ValueError("文字样式数量超过 500")
            if key not in styles and style.font_file.lower().endswith(".shx"):
                warnings.append(f"文字样式 {style.name} 使用 SHX；MyCAD 暂不提供 SHX 绘制")
            if key not in styles:
                if style.name != name:
                    warnings.append(f"文字样式名称冲突：{name} → {style.name}。")
                used_style_names.add(style.name.casefold())
            styles[key] = style
            texts.append(text)
            if handle_map is not None:
                handle = entity.dxf.get("handle")
                if isinstance(handle, str) and handle:
                    handle_map[text.text_id] = handle
        except (ValueError, TypeError, KeyError, DXFTableEntryError) as exc:
            if strict_format:
                raise ValueError(f"{label}：{exc}") from exc
            warnings.append(f"{label} 已跳过：{exc}")
    table = (
        TextStyleTable(tuple(styles.values()), next(iter(styles.values())).style_id)
        if styles
        else None
    )
    return tuple(texts), table, tuple(warnings)
