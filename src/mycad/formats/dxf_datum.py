# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF graphical datum blocks with explicitly MyCAD-specific metadata."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast

from ezdxf.fonts import fonts
from ezdxf.tools.text import plain_text

from mycad.core.drawing_text import TextStyle
from mycad.core.geometric_tolerance import DatumIdentifier
from mycad.core.geometric_tolerance_geometry import (
    circular_datum_geometry,
    datum_leader,
    datum_leader_path,
    datum_triangle,
    surface_indication_geometry,
)
from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata
from mycad.formats.font_outline import outline_text_segments, resolve_outline_font
from mycad.formats.geometric_tolerance_preview import FrameGlyphs
from mycad.formats.text_exchange import read_dxf_text_style

DATUM_APPID = "MYCAD_DATUM"


@dataclass(frozen=True, slots=True)
class DatumGraphicSnapshot:
    """Canvas-local datum box, leader and shaped text, frozen on the GUI thread."""

    datum: DatumIdentifier
    width: float
    height: float
    leader: tuple[tuple[float, float], ...]
    arrow: tuple[tuple[float, float], ...]
    glyphs: FrameGlyphs


@dataclass(frozen=True, slots=True)
class DatumNativeSnapshot:
    """Legacy datum identity and its canvas-measured box in drawing units."""

    datum: DatumIdentifier
    width: float
    height: float


def has_compressed_datum_metadata(document: Any) -> bool:
    """Report whether a remaining datum insert carries compressed metadata."""
    for insert in document.modelspace().query("INSERT"):
        if insert.has_xdata(DATUM_APPID):
            tags = insert.get_xdata(DATUM_APPID)
            if next((tag.value for tag in tags if tag.code == 1000), None) == "Z1":
                return True
    return False


def outline_wide_datum_blocks(document: Any) -> int:
    """Convert wide datum labels to graphic outlines and discard their semantic metadata."""
    converted = 0
    seen: set[str] = set()
    for insert in list(document.modelspace().query("INSERT")):
        if not insert.has_xdata(DATUM_APPID):
            continue
        block_name = str(insert.dxf.name)
        block = document.blocks.get(block_name)
        texts = [item for item in block if item.dxftype() == "TEXT"]
        if not any(
            not math.isclose(float(item.dxf.get("width", 1.0)), 1.0, rel_tol=0.0, abs_tol=1e-12)
            for item in texts
        ):
            continue
        if block_name in seen:
            raise ValueError("共享基准图形块无法安全转换")
        seen.add(block_name)
        outlines: list[tuple[Any, tuple[tuple[tuple[float, float], tuple[float, float]], ...]]] = []
        for item in texts:
            if not math.isclose(float(item.dxf.get("rotation", 0.0)), 0.0, abs_tol=1e-9):
                raise ValueError("旋转的基准文字无法转换")
            style = document.styles.get(str(item.dxf.get("style", "Standard")))
            font_name = resolve_outline_font(style, required=True)
            value = "^" if item.dxf.text == "^  " else plain_text(item.dxf.text)
            height = float(item.dxf.height)
            width = float(item.dxf.get("width", 1.0))
            if not math.isfinite(height) or height <= 0 or not math.isfinite(width) or width <= 0:
                raise ValueError("基准文字尺寸无效")
            outlines.append((item, outline_text_segments(value, font_name, height, width)))
        for item, segments in outlines:
            origin = item.dxf.insert
            for start, end in segments:
                block.add_line(
                    (origin.x + start[0], origin.y + start[1]),
                    (origin.x + end[0], origin.y + end[1]),
                    dxfattribs={"layer": item.dxf.layer},
                )
            block.delete_entity(item)
        insert.discard_xdata(DATUM_APPID)
        converted += 1
    return converted


def _label_parts(label: str) -> list[str]:
    parts: list[str] = []
    for part in re.split(r"([%^])", label):
        chunk = ""
        size = 0
        for char in part:
            char_size = len(char.encode("utf-8"))
            if size + char_size > 255:
                parts.append(chunk)
                chunk, size = "", 0
            chunk += char
            size += char_size
        if chunk:
            parts.append(chunk)
    return parts


def _encoded_label_part(part: str) -> str:
    # A trailing caret is removed by DXF TEXT validators; the extra blank
    # makes the preceding caret a visible glyph rather than a control code.
    return "^  " if part == "^" else part


def _is_literal_datum_text(value: object) -> bool:
    """Accept only unambiguous single-entity DXF text within the model limits."""
    return (
        isinstance(value, str)
        and 0 < len(value) <= 80
        and value == value.strip()
        and value.isprintable()
        and len(value.encode("utf-8")) <= 255
        and not any(character in value for character in ("%", "^", "\\"))
        and plain_text(value) == value
    )


def _datum_font_name(style: TextStyle) -> str:
    font_name = style.font_file
    if not font_name and style.font_family:
        face = fonts.find_best_match(family=style.font_family, style=style.font_style)
        font_name = face.filename if face is not None else ""
    return font_name or "txt"


def datum_box_dimensions(label: str, style: TextStyle) -> tuple[float, float]:
    """Measure a shared, font-aware box in drawing units for display and exchange."""
    scale = style.height_mm / 3.5
    font = fonts.make_font(_datum_font_name(style), style.height_mm)
    width = sum(font.text_width(part) for part in _label_parts(label)) * style.width_factor
    return max(5.0 * scale, 1.6 * scale + width * 1.1), 5.0 * scale


def _signature(block: Any) -> list[object]:
    result: list[object] = []
    for item in block:
        kind = item.dxftype()
        if kind == "LINE":
            result.append([kind, list(item.dxf.start), list(item.dxf.end)])
        elif kind == "SOLID":
            result.append([kind, *[list(item.dxf.get(f"vtx{index}")) for index in range(4)]])
        elif kind == "CIRCLE":
            result.append(
                [
                    kind,
                    list(item.dxf.center),
                    item.dxf.radius,
                    list(item.dxf.get("extrusion", (0, 0, 1))),
                    item.dxf.get("thickness", 0.0),
                ]
            )
        elif kind == "TEXT":
            result.append(
                [
                    kind,
                    item.dxf.text,
                    list(item.dxf.insert),
                    item.dxf.height,
                    item.dxf.get("rotation", 0.0),
                    item.dxf.get("width", 1.0),
                    item.dxf.get("oblique", 0.0),
                    item.dxf.get("style", "Standard"),
                    item.dxf.get("halign", 0),
                    item.dxf.get("valign", 0),
                    list(item.dxf.get("extrusion", (0, 0, 1))),
                ]
            )
        else:
            result.append([kind])
    return result


def freeze_datum_blocks(document: Any, snapshots: Mapping[str, DatumGraphicSnapshot]) -> int:
    """Replace validated datum blocks with the frozen canvas geometry and filled text."""
    if not snapshots:
        return 0
    inserts = list(document.modelspace().query("INSERT"))
    block_counts: dict[str, int] = {}
    for insert in inserts:
        name = str(insert.dxf.name)
        block_counts[name] = block_counts.get(name, 0) + 1
    seen: set[str] = set()
    for insert in inserts:
        if not insert.has_xdata(DATUM_APPID):
            continue
        tags = tuple(tag.value for tag in insert.get_xdata(DATUM_APPID) if tag.code == 1000)
        decoded: object = json.loads(unpack_annotation_metadata(tags))
        if not isinstance(decoded, Mapping):
            raise ValueError("基准图形快照缺少对象身份")
        payload = cast("Mapping[str, object]", decoded)
        datum = DatumIdentifier.from_mapping(payload.get("datum"))
        if datum.datum_id in seen or datum.datum_id not in snapshots:
            raise ValueError("基准图形快照与导出对象不匹配")
        snapshot = snapshots[datum.datum_id]
        name = str(insert.dxf.name)
        block = document.blocks.get(name)
        if (
            snapshot.datum != datum
            or block is None
            or block_counts[name] != 1
            or payload.get("signature") != _signature(block)
            or any(item.dxftype() not in ("LINE", "TEXT", "SOLID", "CIRCLE") for item in block)
            or not math.isclose(float(insert.dxf.get("xscale", 1)), 1.0, abs_tol=1e-12)
            or not math.isclose(float(insert.dxf.get("yscale", 1)), 1.0, abs_tol=1e-12)
            or not math.isclose(float(insert.dxf.get("rotation", 0)), 0.0, abs_tol=1e-12)
            or tuple(insert.dxf.insert)[:2] != datum.position_mm
        ):
            raise ValueError("基准图形快照与原生块内容不匹配")
        if (
            isinstance(snapshot.width, bool)
            or isinstance(snapshot.height, bool)
            or not math.isfinite(snapshot.width)
            or not math.isfinite(snapshot.height)
            or snapshot.width <= 0
            or snapshot.height <= 0
            or len(snapshot.leader) > 66
            or len(snapshot.arrow) not in (0, 3)
            or not snapshot.glyphs
            or len(snapshot.glyphs) > 4096
        ):
            raise ValueError("基准图形快照尺寸无效")
        if datum.layout_mode == "shared" and datum.symbol_style != "circle":
            lines = [item for item in block if item.dxftype() == "LINE"]
            if len(lines) < 4 or not (
                math.isclose(snapshot.width, float(lines[-4].dxf.end.x), rel_tol=1e-9, abs_tol=1e-7)
                and math.isclose(
                    snapshot.height, -float(lines[-3].dxf.end.y), rel_tol=1e-9, abs_tol=1e-7
                )
            ):
                raise ValueError("基准图形快照与标注框尺寸不匹配")
        if datum.symbol_style == "circle":
            circles = [item for item in block if item.dxftype() == "CIRCLE"]
            if (
                len(circles) != 1
                or not math.isclose(snapshot.width, snapshot.height, abs_tol=1e-7)
                or not math.isclose(snapshot.width, 2 * float(circles[0].dxf.radius), abs_tol=1e-7)
            ):
                raise ValueError("圆圈基准图形快照与尺寸不匹配")
        if any(
            not math.isfinite(value)
            for point in (*snapshot.leader, *snapshot.arrow)
            for value in point
        ):
            raise ValueError("基准图形快照引线无效")
        target = datum.target_mm
        if datum.surface_indication is not None:
            _, _, target = surface_indication_geometry(target, datum.surface_indication)
        local_target = (target[0] - datum.position_mm[0], target[1] - datum.position_mm[1])
        expected_leader = (
            datum_leader_path(
                (0.0, 0.0, snapshot.width, -snapshot.height), local_target, datum.leader_offsets
            )
            if datum.leader_visible
            else ()
        )
        if datum.symbol_style == "circle":
            radius = snapshot.width / 2
            _, expected_leader, _ = circular_datum_geometry(
                (radius, -radius),
                local_target,
                radius,
                radius * 1.6,
                bar_direction=datum.bar_direction,
            )
        if len(snapshot.leader) != len(expected_leader) or any(
            not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-7)
            for point, expected_point in zip(snapshot.leader, expected_leader, strict=True)
            for actual, expected in zip(point, expected_point, strict=True)
        ):
            raise ValueError("基准图形快照引线与对象不匹配")
        if datum.symbol_style == "circle" and snapshot.arrow:
            raise ValueError("圆圈基准不能有主引线箭头")
        if datum.symbol_style != "circle" and (
            (datum.arrow_style == "none" and snapshot.arrow)
            or (datum.arrow_style != "none" and snapshot.leader and not snapshot.arrow)
        ):
            raise ValueError("基准图形快照箭头与样式不匹配")
        if snapshot.arrow and (
            not snapshot.leader
            or any(
                not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-7)
                for actual, expected in zip(snapshot.arrow[0], snapshot.leader[-1], strict=True)
            )
        ):
            raise ValueError("基准图形快照箭头与引线不匹配")
        total_points = 0
        for contours in snapshot.glyphs:
            if not contours or len(contours) > 512:
                raise ValueError("基准图形字形轮廓无效")
            for contour in contours:
                total_points += len(contour)
                if len(contour) < 3 or total_points > 200000:
                    raise ValueError("基准图形字形轮廓尺寸无效")
                if any(
                    not math.isfinite(x)
                    or not math.isfinite(y)
                    or x < -1e-7
                    or x > snapshot.width + 1e-7
                    or y < -1e-7
                    or y > snapshot.height + 1e-7
                    for x, y in contour
                ):
                    raise ValueError("基准图形字形轮廓超出标注框")
        for entity in list(block):
            block.delete_entity(entity)
        for start, end in zip(snapshot.leader, snapshot.leader[1:], strict=False):
            block.add_line(start, end)
        if snapshot.arrow and datum.arrow_style == "open":
            for start, end in zip(
                snapshot.arrow, (*snapshot.arrow[1:], snapshot.arrow[0]), strict=True
            ):
                block.add_line(start, end)
        box = (
            (0.0, 0.0),
            (snapshot.width, 0.0),
            (snapshot.width, -snapshot.height),
            (0.0, -snapshot.height),
            (0.0, 0.0),
        )
        if datum.symbol_style == "circle":
            radius = snapshot.width / 2
            _, _, bar = circular_datum_geometry(
                (radius, -radius),
                local_target,
                radius,
                radius * 1.6,
                bar_direction=datum.bar_direction,
            )
            block.add_circle((radius, -radius), radius)
            block.add_line(*bar, dxfattribs={"lineweight": 50})
        else:
            for start, end in zip(box, box[1:], strict=False):
                block.add_line(start, end)
        if snapshot.arrow and datum.arrow_style == "filled":
            block.add_solid((*snapshot.arrow, snapshot.arrow[-1]))
        for contours in snapshot.glyphs:
            hatch = block.add_hatch()
            for contour in contours:
                hatch.paths.add_polyline_path(
                    [(x, -y) for x, y in contour], is_closed=True, flags=0
                )
        insert.discard_xdata(DATUM_APPID)
        seen.add(datum.datum_id)
    if seen != set(snapshots):
        raise ValueError("基准图形快照与导出对象不匹配")
    return len(seen)


def write_datum(
    document: Any,
    datum: DatumIdentifier,
    index: int,
    *,
    style: TextStyle | None = None,
    native_style: str = "Standard",
    legacy_snapshot: DatumNativeSnapshot | None = None,
    handle_out: list[str] | None = None,
) -> bool:
    block = document.blocks.new(name=f"MYCAD_DATUM_{index}")
    style = style or TextStyle()
    scale = style.height_mm / 3.5
    font_name = style.font_file or str(document.styles.get(native_style).dxf.get("font", "txt"))
    if not font_name and style.font_family:
        face = fonts.find_best_match(family=style.font_family, style=style.font_style)
        font_name = face.filename if face is not None else ""
    font = fonts.make_font(font_name, style.height_mm)
    if datum.layout_mode == "shared":
        font = fonts.make_font(_datum_font_name(style), style.height_mm)
    # DXF TEXT interprets %%x and ^x as control codes. Splitting the two
    # introducers into separate entities preserves their literal appearance.
    parts = _label_parts(datum.label)
    width = max(
        5.0 * scale,
        1.6 * scale + sum(font.text_width(part) for part in parts) * style.width_factor * 1.1,
    )
    height = 5 * scale
    if datum.layout_mode == "shared":
        width, height = datum.box_size_mm or datum_box_dimensions(datum.label, style)
    elif legacy_snapshot is not None:
        width, height = legacy_snapshot.width, legacy_snapshot.height
    if datum.symbol_style == "circle":
        width = height = max(width, height)
    primary_target = datum.target_mm
    if datum.surface_indication is not None:
        _, _, primary_target = surface_indication_geometry(
            datum.target_mm, datum.surface_indication
        )
    dx = primary_target[0] - datum.position_mm[0]
    dy = primary_target[1] - datum.position_mm[1]
    leader_path = (
        datum_leader_path((0, 0, width, -height), (dx, dy), datum.leader_offsets)
        if datum.leader_visible and datum.symbol_style != "circle"
        else ()
    )
    if datum.symbol_style == "circle":
        if not datum.leader_visible or datum.surface_indication is not None:
            raise ValueError("圆圈基准需要普通引线")
        radius = width / 2
        circle, connector, bar = circular_datum_geometry(
            (radius, -radius), (dx, dy), radius, radius * 1.6, bar_direction=datum.bar_direction
        )
        block.add_circle(circle[0], circle[1])
        block.add_line(*connector)
        block.add_line(*bar, dxfattribs={"lineweight": 50})
    for start, end in zip(leader_path, leader_path[1:], strict=False):
        block.add_line(start, end)
    triangle = (
        datum_triangle(
            leader_path[-2],
            leader_path[-1],
            min(
                (datum.surface_indication.arrow_size_mm if datum.surface_indication else None)
                or (2.5 if legacy_snapshot is not None else 2.5 * scale),
                math.dist(*leader_path[-2:]),
            ),
        )
        if leader_path and datum.arrow_style != "none"
        else ()
    )
    if triangle and datum.arrow_style == "open":
        for start, end in zip(triangle, (*triangle[1:], triangle[0]), strict=True):
            block.add_line(start, end)
    for start, end in (
        []
        if datum.symbol_style == "circle"
        else [
            ((0, 0), (width, 0)),
            ((width, 0), (width, -height)),
            ((width, -height), (0, -height)),
            ((0, -height), (0, 0)),
        ]
    ):
        block.add_line(start, end)
    if triangle and datum.arrow_style == "filled":
        block.add_solid((triangle[0], triangle[1], triangle[2], triangle[2]))
    cursor = 0.8 * scale
    if datum.layout_mode == "shared" or legacy_snapshot is not None:
        total_width = sum(font.text_width(part) for part in parts) * style.width_factor
        cursor = max(0.0, (width - total_width) / 2)
    for part in parts:
        encoded = _encoded_label_part(part)
        block.add_text(
            encoded,
            dxfattribs={
                "insert": (
                    cursor,
                    -(height + style.height_mm) / 2
                    if legacy_snapshot is not None or datum.symbol_style == "circle"
                    else -4.0 * scale,
                ),
                "height": style.height_mm,
                "width": style.width_factor,
                "style": native_style,
            },
        )
        cursor += font.text_width(part) * style.width_factor
    native = document.modelspace().add_blockref(
        block.name, datum.position_mm, dxfattribs={"layer": datum.layer_name}
    )
    metadata: dict[str, object] = {
        "datum": datum.to_mapping(),
        "signature": _signature(block),
        "layout": 5
        if datum.symbol_style == "circle"
        else 4
        if not datum.leader_visible
        else 3
        if datum.leader_offsets
        else 2,
    }
    if datum.text_style_id is not None:
        metadata["text_style_snapshot"] = {
            "source": style.to_mapping(),
            "native": read_datum_text_style(document, native, 1.0).to_mapping(),
        }
    payload = json.dumps(
        metadata,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    metadata_parts = pack_annotation_metadata(payload)
    native.set_xdata(DATUM_APPID, [(1000, part) for part in metadata_parts])
    if handle_out is not None:
        handle_out.append(str(native.dxf.handle))
    return bool(metadata_parts and metadata_parts[0] == "Z1")


def read_datum_text_style(document: Any, entity: Any, scale: float) -> TextStyle:
    """Read the effective uniform native TEXT style from a validated datum block."""
    block = document.blocks.get(entity.dxf.name)
    texts = [item for item in block if item.dxftype() == "TEXT"]
    if not texts:
        raise ValueError("基准图形块缺少文字")
    first = texts[0]
    name = str(first.dxf.get("style", "Standard"))
    height = float(first.dxf.get("height", 0.0))
    width = float(first.dxf.get("width", 1.0))
    if any(
        str(item.dxf.get("style", "Standard")).casefold() != name.casefold()
        or float(item.dxf.get("height", 0.0)) != height
        or float(item.dxf.get("width", 1.0)) != width
        for item in texts
    ):
        raise ValueError("基准文字样式不一致")
    font = read_dxf_text_style(document, name, scale)
    native_style = document.styles.get(name)
    fixed_height = float(native_style.dxf.get("height", 0.0))
    if not math.isfinite(fixed_height) or fixed_height < 0:
        raise ValueError("基准字体表字高无效")
    if (
        fixed_height > 0 and not math.isclose(fixed_height, height, rel_tol=0.0, abs_tol=1e-9)
    ) or not math.isclose(font.width_factor, width, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("基准字体表与文字图元的字高或宽度不一致")
    return replace(font, height_mm=height * scale, width_factor=width)


def read_datum(
    document: Any,
    entity: Any,
    values: tuple[str, ...],
    scale: float,
    *,
    warnings: list[str] | None = None,
) -> DatumIdentifier:
    payload = json.loads(unpack_annotation_metadata(values))
    datum = DatumIdentifier.from_mapping(payload["datum"])
    if (datum.symbol_style == "circle") != (payload.get("layout") == 5):
        raise ValueError("基准样式与图形布局不一致")
    original_label = datum.label
    block = document.blocks.get(entity.dxf.name)
    if block is None:
        raise ValueError("基准图形块已修改，无法安全恢复结构")
    signature = _signature(block)
    saved_signature = cast("object", payload["signature"])
    renamed = False
    if signature != saved_signature:
        if datum.symbol_style == "circle":
            raise ValueError("圆圈基准图形块已修改，无法安全恢复结构")
        text_indices = [
            index
            for index, item in enumerate(signature)
            if isinstance(item, list) and item[0] == "TEXT"
        ]
        if (
            datum.layout_mode != "shared"
            or not isinstance(saved_signature, list)
            or not text_indices
            or len(signature) != len(cast("list[object]", saved_signature))
        ):
            raise ValueError("基准图形块已修改，无法安全恢复结构")
        original_parts = [_encoded_label_part(part) for part in _label_parts(datum.label)]
        if len(original_parts) != len(text_indices):
            raise ValueError("基准图形块已修改，无法安全恢复结构")
        restored_signature = list(signature)
        for index, original_part in zip(text_indices, original_parts, strict=True):
            raw_current = signature[index]
            raw_saved = cast("list[object]", saved_signature)[index]
            if not isinstance(raw_current, list) or not isinstance(raw_saved, list):
                raise ValueError("基准图形块已修改，无法安全恢复结构")
            current, saved = cast("list[object]", raw_current), cast("list[object]", raw_saved)
            if (
                len(current) < 2
                or len(saved) < 2
                or saved[0] != "TEXT"
                or saved[1] != original_part
                or (current[1] != original_part and not _is_literal_datum_text(current[1]))
            ):
                raise ValueError("基准图形块已修改，无法安全恢复结构")
            restored_signature[index] = [current[0], saved[1], *current[2:]]
        if restored_signature != saved_signature:
            raise ValueError("基准图形块已修改，无法安全恢复结构")
        if any(
            str(item.dxf.get("layer", "0")) != "0"
            or int(item.dxf.get("color", 256)) != 256
            or str(item.dxf.get("linetype", "BYLAYER")).upper() != "BYLAYER"
            or int(item.dxf.get("lineweight", -1)) != -1
            or int(item.dxf.get("invisible", 0)) != 0
            or item.dxf.hasattr("true_color")
            or item.dxf.hasattr("transparency")
            for item in block
        ):
            raise ValueError("基准图形块外观已修改，无法安全恢复结构")
        renamed = True
    label = "".join(
        "^" if item.dxf.text == "^  " else plain_text(item.dxf.text)
        for item in block
        if item.dxftype() == "TEXT"
    )
    leaders = [item for item in block if item.dxftype() == "LINE"]
    if datum.arrow_style == "open" and datum.leader_visible and len(leaders) >= 7:
        leaders = [*leaders[:-7], *leaders[-4:]]
    primary_target = datum.target_mm
    if datum.surface_indication is not None:
        _, _, primary_target = surface_indication_geometry(
            datum.target_mm, datum.surface_indication
        )
    delta = (
        primary_target[0] - datum.position_mm[0],
        primary_target[1] - datum.position_mm[1],
        0.0,
    )
    if datum.symbol_style == "circle" and payload.get("layout") == 5:
        circles = [item for item in block if item.dxftype() == "CIRCLE"]
        if len(circles) != 1 or len(leaders) != 2:
            raise ValueError("圆圈基准图形块结构无效")
        if int(leaders[1].dxf.get("lineweight", -1)) != 50:
            raise ValueError("圆圈基准短线样式已修改，无法安全恢复结构")
        radius = float(circles[0].dxf.radius)
        if datum.box_size_mm is not None and not math.isclose(
            2 * radius, max(datum.box_size_mm), rel_tol=1e-9, abs_tol=1e-7
        ):
            raise ValueError("圆圈基准尺寸与元数据不一致")
        expected_circle, connector, bar = circular_datum_geometry(
            (radius, -radius),
            (delta[0], delta[1]),
            radius,
            radius * 1.6,
            bar_direction=datum.bar_direction,
        )
        consistent = math.dist(circles[0].dxf.center, (*expected_circle[0], 0)) <= 1e-9
        consistent = consistent and all(
            math.dist(line.dxf.start, (*start, 0.0)) <= 1e-9
            and math.dist(line.dxf.end, (*end, 0.0)) <= 1e-9
            for line, (start, end) in zip(leaders, (connector, bar), strict=True)
        )
    elif payload.get("layout") == 4:
        consistent = (
            not datum.leader_visible
            and len(leaders) == 4
            and not any(item.dxftype() == "SOLID" for item in block)
        )
    elif payload.get("layout") == 3 and len(leaders) >= 4:
        outline = leaders[-4:]
        width = max(float(item.dxf.start.x) for item in outline)
        height = min(float(item.dxf.start.y) for item in outline)
        expected_path = datum_leader_path(
            (0, 0, width, height), (delta[0], delta[1]), datum.leader_offsets
        )
        pairs = tuple(zip(expected_path, expected_path[1:], strict=False))
        actual = leaders[:-4]
        consistent = len(actual) == len(pairs) and all(
            math.dist(line.dxf.start, (*start, 0.0)) <= 1e-9
            and math.dist(line.dxf.end, (*end, 0.0)) <= 1e-9
            for line, (start, end) in zip(actual, pairs, strict=True)
        )
    elif payload.get("layout") == 2 and len(leaders) in (4, 5):
        outline = leaders[-4:]
        width = max(float(item.dxf.start.x) for item in outline)
        height = min(float(item.dxf.start.y) for item in outline)
        expected = datum_leader((0, 0, width, height), (delta[0], delta[1]))
        consistent = (
            len(leaders) == 4
            if expected is None
            else len(leaders) == 5
            and math.dist(leaders[0].dxf.start, (*expected[0], 0.0)) <= 1e-9
            and math.dist(leaders[0].dxf.end, (*expected[1], 0.0)) <= 1e-9
        )
    else:
        consistent = bool(leaders) and math.dist(leaders[0].dxf.start, (0, 0, 0)) <= 1e-9
        consistent = consistent and math.dist(leaders[0].dxf.end, delta) <= 1e-9
    if datum.box_size_mm is not None and datum.symbol_style != "circle":
        outline = leaders[-4:]
        consistent = consistent and len(outline) == 4
        if len(outline) == 4:
            width = max(float(item.dxf.start.x) for item in outline)
            height = -min(float(item.dxf.start.y) for item in outline)
            consistent = consistent and math.dist((width, height), datum.box_size_mm) <= 1e-9
    if (label != datum.label and not renamed) or not consistent:
        raise ValueError("基准元数据与图形块文字、框尺寸或指向点不一致")
    if renamed:
        outline = leaders[-4:]
        if len(outline) != 4:
            raise ValueError("基准图形块已修改，无法安全恢复结构")
        width = max(float(item.dxf.start.x) for item in outline) * scale
        height = -min(float(item.dxf.start.y) for item in outline) * scale
        font = read_datum_text_style(document, entity, scale)
        face = fonts.make_font(_datum_font_name(font), font.height_mm)
        texts = [item for item in block if item.dxftype() == "TEXT"]
        limits = [float(item.dxf.insert.x) * scale for item in texts[1:]] + [width]
        if font.height_mm > height + 1e-9:
            raise ValueError("基准名称无法放入原文字框")
        for text, limit in zip(texts, limits, strict=True):
            value = "^" if text.dxf.text == "^  " else plain_text(text.dxf.text)
            text_width = face.text_width(value) * font.width_factor
            text_x = float(text.dxf.insert.x) * scale
            if not math.isfinite(text_width) or text_x < 0 or text_x + text_width > limit + 1e-9:
                raise ValueError("基准名称无法放入原文字框或文字片段重叠")
        datum = replace(datum, label=label, box_size_mm=(width / scale, height / scale))
    if any(
        not math.isclose(float(entity.dxf.get(name, default)), default, abs_tol=1e-9)
        for name, default in (("xscale", 1.0), ("yscale", 1.0), ("zscale", 1.0), ("rotation", 0.0))
    ):
        raise ValueError("基准图形块旋转或缩放后无法安全恢复结构")
    position = entity.dxf.insert
    extrusion = entity.dxf.get("extrusion", (0, 0, 1))
    if math.dist(extrusion, (0, 0, 1)) > 1e-9:
        raise ValueError("基准图形块不在 XY 平面")
    if not math.isclose(position.z, 0.0, abs_tol=1e-9):
        raise ValueError("基准图形块不在 XY 平面")
    target = (
        position.x + datum.target_mm[0] - datum.position_mm[0],
        position.y + datum.target_mm[1] - datum.position_mm[1],
    )
    indication = datum.surface_indication
    if indication is not None:
        indication = replace(
            indication,
            reference_start_offset_mm=tuple(
                v * scale for v in indication.reference_start_offset_mm
            ),
            reference_end_offset_mm=tuple(v * scale for v in indication.reference_end_offset_mm),
            leader_offsets_mm=tuple(
                (x * scale, y * scale) for x, y in indication.leader_offsets_mm
            ),
            arrow_size_mm=(
                indication.arrow_size_mm * scale if indication.arrow_size_mm is not None else None
            ),
        )
    result = replace(
        datum,
        position_mm=(position.x * scale, position.y * scale),
        target_mm=(target[0] * scale, target[1] * scale),
        leader_offsets=tuple((x * scale, y * scale) for x, y in datum.leader_offsets),
        box_size_mm=(
            (datum.box_size_mm[0] * scale, datum.box_size_mm[1] * scale)
            if datum.box_size_mm is not None
            else None
        ),
        surface_indication=indication,
        layer_name=entity.dxf.layer,
    )
    if renamed and warnings is not None:
        warnings.append(f"基准名称由 {original_label} 修改为 {label}；文字已重新排版，请检查关联。")
    return result
