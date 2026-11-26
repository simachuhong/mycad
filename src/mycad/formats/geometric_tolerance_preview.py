# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Preview-only DXF graphics for native tolerance entities.

The original export bytes never contain these additional graphics. Text widths
are estimated, so this is a semantic preview, not a CAD application's typesetting.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from ezdxf.fonts import fonts
from ezdxf.lldxf.const import DXFTableEntryError, DXFValueError

from mycad.core.geometric_tolerance import FeatureControlFrame
from mycad.core.geometric_tolerance_symbols import geometric_symbol_commands
from mycad.formats.dxf_xdata import unpack_annotation_metadata
from mycad.formats.font_outline import outline_text_segments, resolve_outline_font
from mycad.formats.geometric_tolerance_codec import decode_rows, encode_rows

if TYPE_CHECKING:
    from ezdxf.document import Drawing

GlyphContours = tuple[tuple[tuple[float, float], ...], ...]
FrameGlyphs = tuple[GlyphContours, ...]


def _positive_finite_width(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(value) and value > 0
    except OverflowError:
        return False


def expand_tolerances_for_preview(
    document: Drawing,
    *,
    outline_wide_text: bool = False,
    strict: bool = False,
    frame_widths: Mapping[str, tuple[tuple[float, ...], ...]] | None = None,
    frame_glyphs: Mapping[str, FrameGlyphs] | None = None,
) -> tuple[int, int]:
    """Replace supported native frames in an in-memory DXF with visible proxies."""
    modelspace = document.modelspace()
    rendered = 0
    unsupported = 0
    seen: set[str] = set()
    if frame_glyphs and (not frame_widths or set(frame_glyphs) != set(frame_widths)):
        raise ValueError("公差框字形快照与布局快照不匹配。")
    for entity in cast("list[Any]", list(modelspace.query("TOLERANCE"))):
        try:
            rows = decode_rows(entity.dxf.content)
        except (AttributeError, ValueError):
            unsupported += 1
            continue
        try:
            memberships = [
                (group, tuple(group))
                for _, group in document.groups
                if any(member is entity for member in group)
            ]
            existing_handles: set[str] = (
                {str(item.dxf.handle) for item in modelspace} if memberships else set()
            )
            widths = None
            glyph_snapshot: FrameGlyphs | None = None
            if frame_widths:
                values = tuple(
                    tag.value for tag in entity.get_xdata("MYCAD_FCF") if tag.code == 1000
                )
                payload: object = json.loads(unpack_annotation_metadata(values))
                if not isinstance(payload, Mapping):
                    raise ValueError("公差框布局快照缺少对象身份")
                frame = FeatureControlFrame.from_mapping(
                    cast("Mapping[str, object]", payload).get("frame")
                )
                if (
                    frame.frame_id in seen
                    or frame.frame_id not in frame_widths
                    or encode_rows(frame.rows) != entity.dxf.content
                ):
                    raise ValueError("公差框布局快照与导出内容不匹配")
                widths = frame_widths[frame.frame_id]
                if frame_glyphs:
                    glyph_snapshot = frame_glyphs[frame.frame_id]
                seen.add(frame.frame_id)
            _draw_frame(
                modelspace,
                entity,
                rows,
                outline_wide_text=outline_wide_text,
                cell_widths=widths,
                glyphs=glyph_snapshot,
            )
        except (
            DXFTableEntryError,
            DXFValueError,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            if strict:
                raise ValueError(f"公差框图形转换失败：{exc}") from exc
            unsupported += 1
            continue
        if memberships:
            replacements = tuple(
                item for item in modelspace if str(item.dxf.handle) not in existing_handles
            )
            for group, members in memberships:
                group.set_data(
                    replacement
                    for member in members
                    for replacement in (replacements if member is entity else (member,))
                )
        for leader in modelspace.query("LEADER"):
            if (
                leader.has_xdata("MYCAD_FCF_LEADER")
                and leader.dxf.get("annotation_handle") == entity.dxf.handle
            ):
                leader.dxf.discard("annotation_handle")
                leader.discard_xdata("MYCAD_FCF_LEADER")
        modelspace.delete_entity(entity)
        rendered += 1
    if frame_widths and seen != set(frame_widths):
        raise ValueError("公差框布局快照与导出对象不匹配。")
    return rendered, unsupported


def _draw_frame(
    modelspace: Any,
    entity: Any,
    rows: Any,
    *,
    outline_wide_text: bool,
    cell_widths: tuple[tuple[float, ...], ...] | None = None,
    glyphs: FrameGlyphs | None = None,
) -> None:
    insert = entity.dxf.insert
    axis = entity.dxf.x_axis_vector
    angle = math.atan2(axis.y, axis.x)
    cosine, sine = math.cos(angle), math.sin(angle)
    attrs = {"layer": entity.dxf.layer}
    dimstyle_name = str(entity.dxf.get("dimstyle", "Standard"))
    text_style_name = "Standard"
    scale = 1.0
    if dimstyle_name.casefold() != "standard":
        dimstyle = modelspace.doc.dimstyles.get(dimstyle_name)
        text_style_name = str(dimstyle.dxf.get("dimtxsty", "Standard"))
        scale = (
            float(dimstyle.dxf.get("dimtxt", 2.5)) * float(dimstyle.dxf.get("dimscale", 1.0)) / 3.5
        )
    native_style = modelspace.doc.styles.get(text_style_name)
    width_factor = float(native_style.dxf.get("width", 1.0))
    if (
        not math.isfinite(scale)
        or scale <= 0
        or not math.isfinite(width_factor)
        or width_factor <= 0
    ):
        raise ValueError("invalid tolerance text style")
    if cell_widths is not None:
        if len(cell_widths) != len(rows):
            raise ValueError("公差框布局行数不匹配")
        for row, widths in zip(rows, cell_widths, strict=True):
            if (
                len(widths) != 2 + len(row.datums)
                or any(not _positive_finite_width(width) for width in widths)
                or not math.isclose(widths[0], 5.4 * scale, abs_tol=1e-7)
            ):
                raise ValueError("公差框布局单元格尺寸无效")
            minimums = [(1.6 + (3.3 if row.diameter else 0) + (3.5 if row.modifier else 0)) * scale]
            minimums.extend((1.6 + (3.5 if datum.modifier else 0)) * scale for datum in row.datums)
            if any(
                width + 1e-9 < minimum for width, minimum in zip(widths[1:], minimums, strict=True)
            ):
                raise ValueError("公差框布局单元格宽度不足")
    outline = (
        glyphs is None
        and outline_wide_text
        and not math.isclose(width_factor, 1.0, rel_tol=0.0, abs_tol=1e-12)
    )
    font_name = resolve_outline_font(native_style, required=outline)

    def text_width(value: str, height: float) -> float:
        # Match the actual font metrics used by the DXF drawing backend, with
        # a small margin for glyph overhang and substitution differences.
        return max(
            fonts.make_font(font_name, height).text_width(value) * width_factor * 1.1, height * 0.4
        )

    def point(x: float, y: float) -> tuple[float, float]:
        return (
            insert.x + scale * (x * cosine - y * sine),
            insert.y + scale * (x * sine + y * cosine),
        )

    def line(x1: float, y1: float, x2: float, y2: float) -> None:
        modelspace.add_line(point(x1, y1), point(x2, y2), dxfattribs=attrs)

    def box(left: float, bottom: float, width: float, height: float) -> None:
        line(left, bottom, left + width, bottom)
        line(left + width, bottom, left + width, bottom + height)
        line(left + width, bottom + height, left, bottom + height)
        line(left, bottom + height, left, bottom)

    if glyphs is not None:
        if not glyphs or cell_widths is None or len(glyphs) > 4096:
            raise ValueError("公差框字形快照无效")
        max_x = max(sum(row) for row in cell_widths)
        max_y = len(rows) * 6.0 * scale
        total_points = 0
        for contours in glyphs:
            if not contours or len(contours) > 512:
                raise ValueError("公差框字形轮廓无效")
            hatch = modelspace.add_hatch(dxfattribs=attrs)
            for contour in contours:
                total_points += len(contour)
                if len(contour) < 3 or total_points > 200000:
                    raise ValueError("公差框字形轮廓尺寸无效")
                vertices: list[tuple[float, float]] = []
                for gx, gy in contour:
                    if (
                        not _positive_finite_width(gx + 1)
                        or not _positive_finite_width(gy + 1)
                        or gx < -1e-7
                        or gx > max_x + 1e-7
                        or gy < -1e-7
                        or gy > max_y + 1e-7
                    ):
                        raise ValueError("公差框字形轮廓超出布局")
                    vertices.append(point(gx / scale, -gy / scale))
                hatch.paths.add_polyline_path(vertices, is_closed=True, flags=0)

    def text(
        value: str, x: float, y: float, height: float = 3.5, width_ratio: float = 1.0
    ) -> float:
        if outline:
            for start, end in outline_text_segments(
                value, font_name, height, width_factor * width_ratio
            ):
                line(x + start[0], y + start[1], x + end[0], y + end[1])
            return text_width(value, height) * width_ratio
        if len(value.encode("utf-8")) > 255:
            raise ValueError("公差框单格文字超过 255 字节，请缩短内容后导出。")
        modelspace.add_text(
            value,
            dxfattribs={
                **attrs,
                "insert": point(x, y),
                "height": height * scale,
                "style": text_style_name,
                "width": width_factor * width_ratio,
                "rotation": math.degrees(angle),
            },
        )
        return text_width(value, height) * width_ratio

    for index, row in enumerate(rows):
        bottom = -6.0 * (index + 1)
        box(0, bottom, 5.4, 6)
        current = (0.0, 0.0)
        for command, coords in geometric_symbol_commands(row.characteristic):

            def symbol_point(x: float, y: float, bottom: float = bottom) -> tuple[float, float]:
                return (0.8 + x * 3.8, bottom + 4.9 - y * 3.8)

            if command == "move":
                current = symbol_point(coords[0], coords[1])
            elif command == "line":
                end = symbol_point(coords[0], coords[1])
                line(*current, *end)
                current = end
            elif command == "ellipse":
                x, y, width, _height = coords
                center = symbol_point(x + width / 2, y + width / 2)
                modelspace.add_circle(point(*center), width * 1.9 * scale, dxfattribs=attrs)
            else:
                start = current
                c1 = symbol_point(coords[0], coords[1])
                c2 = symbol_point(coords[2], coords[3])
                end = symbol_point(coords[4], coords[5])
                for step in range(1, 13):
                    t = step / 12
                    u = 1 - t
                    new = tuple(
                        u**3 * start[i]
                        + 3 * u * u * t * c1[i]
                        + 3 * u * t * t * c2[i]
                        + t**3 * end[i]
                        for i in range(2)
                    )
                    line(*current, *new)
                    current = (new[0], new[1])
        x = 5.4
        cells = [(f"{row.value:.{row.precision}f}", row.diameter, row.modifier)]
        cells.extend((datum.label, False, datum.modifier) for datum in row.datums)
        for cell_index, (value, diameter, modifier) in enumerate(cells):
            width = (
                cell_widths[index][cell_index + 1] / scale
                if cell_widths is not None
                else 1.6
                + text_width(value, 3.5)
                + (3.3 if diameter else 0)
                + (3.5 if modifier else 0)
            )
            box(x, bottom, width, 6)
            cursor = x + 0.8
            if diameter:
                center = (cursor + 1.45, bottom + 3)
                modelspace.add_circle(point(*center), 1.25 * scale, dxfattribs=attrs)
                line(cursor, bottom + 1.6, cursor + 2.9, bottom + 4.4)
                cursor += 3.3
            if glyphs is None:
                cursor += text(value, cursor, bottom + 1.3)
            if modifier:
                center = (x + width - 2.25 if glyphs is not None else cursor + 1.75, bottom + 3)
                modelspace.add_circle(point(*center), 1.45 * scale, dxfattribs=attrs)
                if glyphs is None:
                    modifier_width = text_width(modifier, 2)
                    fit = min(1.0, 2.3 / modifier_width)
                    text(modifier, center[0] - modifier_width * fit / 2, bottom + 2.2, 2, fit)
            x += width
