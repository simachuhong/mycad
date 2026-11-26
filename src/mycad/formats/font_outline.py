# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Resolve portable DXF text styles and generate verified outline segments."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ezdxf.addons import text2path
from ezdxf.fonts import fonts


def resolve_outline_font(style: Any, *, required: bool) -> str:
    name = str(style.dxf.get("font", "txt"))
    family, italic, bold = style.get_extended_font_data()
    if not name and family:
        face = fonts.find_best_match(family=family, italic=italic, weight=700 if bold else 400)
        if face is not None and face.family.casefold() == family.casefold():
            name = face.filename
        elif required:
            raise ValueError(f"字体 {family} 不可用，无法生成可靠的文字轮廓")
    suffix = Path(name).suffix.casefold()
    if required and suffix == ".shx":
        raise ValueError(f"字体 {name} 不可用：暂不支持 SHX 文字轮廓")
    if (
        required
        and suffix in (".ttf", ".otf", ".ttc")
        and fonts.find_font_face(name).filename.casefold() != Path(name).name.casefold()
    ):
        raise ValueError(f"字体文件 {name} 不可用，无法生成可靠的文字轮廓")
    return name


def outline_text_segments(
    value: str, font_name: str, height: float, width_factor: float
) -> tuple[tuple[tuple[float, float], tuple[float, float]], ...]:
    font = fonts.make_font(font_name, height)
    cache: object = getattr(font, "glyph_cache", None)
    cmap: object = getattr(cache, "cmap", None)
    if not isinstance(cmap, Mapping):
        raise ValueError("字体字符覆盖不可核验，无法生成可靠的文字轮廓")
    missing = "".join(
        dict.fromkeys(char for char in value if not char.isspace() and ord(char) not in cmap)
    )
    if missing:
        raise ValueError(f"字体缺少字符：{missing}")
    paths = text2path.make_paths_from_str(value, fonts.find_font_face(font_name), size=height)
    if not paths and value.strip():
        raise ValueError("文字没有可用的字体轮廓")
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for path in paths:
        vertices = iter(path.flattening(distance=0.03))
        previous = next(vertices, None)
        for vertex in vertices:
            if previous is not None:
                segments.append(
                    ((previous.x * width_factor, previous.y), (vertex.x * width_factor, vertex.y))
                )
            previous = vertex
    return tuple(segments)
