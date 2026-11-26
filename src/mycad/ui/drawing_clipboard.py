# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Validated interchange format for copied independent 2D geometry."""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Mapping
from dataclasses import replace
from typing import cast
from uuid import uuid4

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage, QImageWriter

from mycad.core.dimension_interchange import (
    reconcile_clipboard_fonts as reconcile_clipboard_fonts,
)
from mycad.core.dimension_interchange import (
    reconcile_clipboard_styles as reconcile_clipboard_styles,
)
from mycad.core.dimension_styles import DimensionStyleTable
from mycad.core.drawing_raster import MAX_RASTER_PIXELS, DrawingRaster
from mycad.core.drawing_text import TextStyleTable
from mycad.core.sketch import Point2D, PolylineEntity, RectangleEntity, Sketch, SketchEntity
from mycad.core.sketch_constraints import SketchConstraint
from mycad.core.sketch_edit import copy_entities
from mycad.core.sketch_references import resolve_point_reference

DRAWING_CLIPBOARD_MIME = "application/x-mycad-drawing2d+json"
DRAWING_RASTER_MIME = "application/x-mycad-raster-size+json"
DRAWING_RASTER_GROUP_MIME = "application/x-mycad-raster-group+json"
DRAWING_MIXED_CLIPBOARD_MIME = "application/x-mycad-drawing-with-images+json"
MAX_MIXED_CLIPBOARD_BYTES = 32_000_000
_MAX_RASTER_GROUP_BYTES = MAX_MIXED_CLIPBOARD_BYTES
_MAX_BYTES = 1_000_000


def encode_mixed_clipboard(
    sketch: Sketch,
    images: tuple[DrawingRaster, ...],
    styles: DimensionStyleTable | None = None,
    text_styles: TextStyleTable | None = None,
) -> bytes:
    """Encode geometry and pictures in one bounded clipboard record."""
    if not 1 <= len(images) <= 1000 or len({item.image_id for item in images}) != len(images):
        raise ValueError("请选择有效且身份唯一的图片。")
    record = {
        "format": "mycad-drawing-with-images",
        "version": 1,
        "sketch": base64.b64encode(encode_drawing_clipboard(sketch, styles, text_styles)).decode(
            "ascii"
        ),
        "images": [image.to_mapping(version=2) for image in images],
    }
    data = json.dumps(record, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > _MAX_RASTER_GROUP_BYTES:
        raise ValueError("剪贴板数据过大。")
    return data


def decode_mixed_clipboard(data: bytes) -> tuple[Sketch, tuple[DrawingRaster, ...]]:
    """Validate a mixed clipboard record before starting a paste."""
    sketch, images, _styles = decode_mixed_clipboard_data(data)
    return sketch, images


def decode_mixed_clipboard_data(
    data: bytes,
) -> tuple[Sketch, tuple[DrawingRaster, ...], DimensionStyleTable | None]:
    """Validate a mixed record and preserve the contained dimension styles."""
    sketch, images, styles, text_styles = decode_mixed_clipboard_full(data)
    if text_styles is not None:
        raise ValueError("此粘贴路径暂不支持携带标注文字样式。")
    return sketch, images, styles


def decode_mixed_clipboard_full(
    data: bytes,
) -> tuple[Sketch, tuple[DrawingRaster, ...], DimensionStyleTable | None, TextStyleTable | None]:
    """Read mixed geometry, images, dimension styles and their font styles."""
    if not data or len(data) > _MAX_RASTER_GROUP_BYTES:
        raise ValueError("剪贴板数据无效或过大。")
    try:
        value: object = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("剪贴板数据无效。")
        record = cast("dict[str, object]", value)
        if (
            set(record) != {"format", "version", "sketch", "images"}
            or record["format"] != "mycad-drawing-with-images"
            or type(record["version"]) is not int
            or record["version"] != 1
            or not isinstance(record["sketch"], str)
            or not isinstance(record["images"], list)
        ):
            raise ValueError("剪贴板数据无效。")
        sketch, styles, text_styles = decode_drawing_clipboard_full(
            base64.b64decode(record["sketch"], validate=True)
        )
        images = tuple(
            DrawingRaster.from_mapping(item) for item in cast("list[object]", record["images"])
        )
        if not 1 <= len(images) <= 1000 or len({item.image_id for item in images}) != len(images):
            raise ValueError("图片数量或身份无效。")
        return sketch, images, styles, text_styles
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("混合剪贴板数据无效。") from exc


def raster_from_clipboard_image(
    image: QImage, layer_name: str, size_data: bytes | None = None
) -> DrawingRaster:
    """Encode a clipboard image as a bounded embedded PNG reference."""
    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        raise ValueError("剪贴板图片无效。")
    if image.width() * image.height() > MAX_RASTER_PIXELS:
        raise ValueError("剪贴板图片像素数量超出限制。")
    width_mm = 100.0
    height_mm = width_mm * image.height() / image.width()
    angle_deg = 0.0
    mirrored = False
    if size_data is not None:
        try:
            if len(size_data) > 1024:
                raise ValueError("图片尺寸数据过大。")
            value: object = json.loads(size_data)
            if not isinstance(value, list):
                raise ValueError("图片尺寸数据无效。")
            sizes = cast("list[object]", value)
            if len(sizes) not in (2, 4):
                raise ValueError("图片尺寸数据无效。")
            if any(
                isinstance(number, bool)
                or not isinstance(number, int | float)
                or not math.isfinite(number)
                or number <= 0
                for number in sizes[:2]
            ):
                raise ValueError("图片尺寸数据无效。")
            width_mm, height_mm = float(cast("float", sizes[0])), float(cast("float", sizes[1]))
            if len(sizes) == 4:
                angle, mirror = sizes[2:]
                if (
                    isinstance(angle, bool)
                    or not isinstance(angle, int | float)
                    or not math.isfinite(angle)
                    or not isinstance(mirror, bool)
                ):
                    raise ValueError("图片变换数据无效。")
                angle_deg, mirrored = float(angle), mirror
        except (UnicodeDecodeError, json.JSONDecodeError, OverflowError) as exc:
            raise ValueError("图片尺寸数据无效。") from exc
    output = QByteArray()
    buffer = QBuffer(output)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not QImageWriter(buffer, b"PNG").write(
        image
    ):
        raise ValueError("无法读取剪贴板图片。")
    buffer.close()
    return DrawingRaster(
        uuid4().hex,
        base64.b64encode(bytes(output.data())).decode("ascii"),
        (0, 0),
        width_mm,
        height_mm,
        layer_name,
        angle_deg,
        mirrored,
    )


def encode_raster_group(images: tuple[DrawingRaster, ...]) -> bytes:
    """Encode a bounded set of pictures for copying between MyCAD drawings."""
    if not 2 <= len(images) <= 1000 or len({image.image_id for image in images}) != len(images):
        raise ValueError("请选择有效且身份唯一的多张图片。")
    if sum(len(image.png_base64) for image in images) > _MAX_RASTER_GROUP_BYTES:
        raise ValueError("图片总大小超出剪贴板限制。")
    data = json.dumps(
        {
            "format": "mycad-raster-group",
            "version": 1,
            "images": [image.to_mapping(version=2) for image in images],
        },
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(data) > _MAX_RASTER_GROUP_BYTES:
        raise ValueError("图片总大小超出剪贴板限制。")
    return data


def decode_raster_group(data: bytes) -> tuple[DrawingRaster, ...]:
    """Validate clipboard data before accepting its pictures."""
    if not data or len(data) > _MAX_RASTER_GROUP_BYTES:
        raise ValueError("图片剪贴板数据无效或超出限制。")
    try:
        value: object = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("图片剪贴板数据无效。") from exc
    if not isinstance(value, dict):
        raise ValueError("图片剪贴板数据无效。")
    record = cast("dict[str, object]", value)
    if (
        set(record) != {"format", "version", "images"}
        or record["format"] != "mycad-raster-group"
        or type(record["version"]) is not int
        or record["version"] != 1
        or not isinstance(record["images"], list)
    ):
        raise ValueError("图片剪贴板数据无效。")
    raw_images = cast("list[object]", record["images"])
    if not 2 <= len(raw_images) <= 1000:
        raise ValueError("图片剪贴板数量无效。")
    images = tuple(DrawingRaster.from_mapping(item) for item in raw_images)
    if len({image.image_id for image in images}) != len(images):
        raise ValueError("图片身份重复。")
    return images


def _validate_references(sketch: Sketch) -> None:
    entities = {entity.entity_id: entity for entity in sketch.entities}
    for constraint in sketch.constraints:
        for ref in constraint.references:
            entity = entities.get(ref.entity_id)
            if entity is None:
                raise ValueError("复制的约束引用了未选择的图元。")
            if ref.kind == "segment":
                if isinstance(entity, RectangleEntity):
                    count = 4
                elif isinstance(entity, PolylineEntity):
                    count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
                else:
                    raise ValueError("约束引用的图元没有可用的线段。")
                if ref.index is None or ref.index >= count:
                    raise ValueError("约束引用的线段不存在。")
            elif ref.kind != "geometry" and resolve_point_reference(ref, entities) is None:
                raise ValueError("约束引用的点不存在。")


def encode_drawing_clipboard(
    sketch: Sketch,
    styles: DimensionStyleTable | None = None,
    text_styles: TextStyleTable | None = None,
) -> bytes:
    """Serialize selected geometry using the existing neutral sketch format."""
    if not sketch.entities:
        raise ValueError("请选择要复制的二维图元。")
    _validate_references(sketch)
    envelope: dict[str, object] = {
        "format": "mycad-drawing-clipboard",
        "version": 1,
        "sketch": sketch.to_state_mapping(),
    }
    names = {c.style_name.casefold() for c in sketch.constraints if c.style_name is not None}
    if names and styles is not None:
        selected = tuple(style for style in styles.styles if style.name.casefold() in names)
        if {style.name.casefold() for style in selected} != names:
            raise ValueError("所选尺寸引用了不存在的标注样式。")
        envelope["version"] = 2
        envelope["styles"] = DimensionStyleTable(selected, selected[0].name).to_mapping()
        used_fonts = {style.text_style_id for style in selected if style.text_style_id is not None}
        if used_fonts:
            if text_styles is None:
                raise ValueError("所选尺寸引用的文字样式不可用。")
            selected_fonts = tuple(
                style for style in text_styles.styles if style.style_id in used_fonts
            )
            if {style.style_id for style in selected_fonts} != used_fonts:
                raise ValueError("所选尺寸引用了不存在的文字样式。")
            envelope["version"] = 3
            envelope["text_styles"] = TextStyleTable(
                selected_fonts, selected_fonts[0].style_id
            ).to_mapping()
    data = json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(data) > _MAX_BYTES:
        raise ValueError("所选图元超出剪贴板大小限制。")
    return data


def decode_drawing_clipboard(data: bytes) -> Sketch:
    """Reject unrecognized or malformed clipboard data before creating geometry."""
    return decode_drawing_clipboard_data(data)[0]


def decode_drawing_clipboard_data(data: bytes) -> tuple[Sketch, DimensionStyleTable | None]:
    """Read geometry and the complete styles carried by modern clipboard records."""
    sketch, styles, text_styles = decode_drawing_clipboard_full(data)
    if text_styles is not None:
        raise ValueError("此粘贴路径暂不支持携带标注文字样式。")
    return sketch, styles


def decode_drawing_clipboard_full(
    data: bytes,
) -> tuple[Sketch, DimensionStyleTable | None, TextStyleTable | None]:
    """Validate all referenced dimension and text styles in a clipboard record."""
    if not data or len(data) > _MAX_BYTES:
        raise ValueError("剪贴板中没有有效的二维图元。")
    try:
        raw: object = json.loads(data)
        if not isinstance(raw, dict):
            raise ValueError("剪贴板格式不受支持。")
        envelope = cast("Mapping[str, object]", raw)
        if (
            envelope.get("format") != "mycad-drawing-clipboard"
            or type(envelope["version"]) is not int
            or (envelope["version"] == 1 and set(envelope) != {"format", "version", "sketch"})
            or (
                envelope["version"] == 2
                and set(envelope) != {"format", "version", "sketch", "styles"}
            )
            or (
                envelope["version"] == 3
                and set(envelope) != {"format", "version", "sketch", "styles", "text_styles"}
            )
            or envelope["version"] not in (1, 2, 3)
        ):
            raise ValueError("剪贴板格式不受支持。")
        sketch = Sketch.from_mapping(envelope["sketch"])
        if not sketch.entities:
            raise ValueError("剪贴板没有二维图元。")
        _validate_references(sketch)
        styles = (
            DimensionStyleTable.from_mapping(envelope["styles"])
            if envelope["version"] in (2, 3)
            else None
        )
        text_styles = (
            TextStyleTable.from_mapping(envelope["text_styles"])
            if envelope["version"] == 3
            else None
        )
        if styles is not None:
            for constraint in sketch.constraints:
                if constraint.style_name is not None:
                    styles.get(constraint.style_name)
            for style in styles.styles:
                if style.text_style_id is not None:
                    if text_styles is None:
                        raise ValueError("剪贴板缺少标注文字样式。")
                    text_styles.get(style.text_style_id)
        return sketch, styles, text_styles
    except (KeyError, ValueError, UnicodeDecodeError, RecursionError, OverflowError) as exc:
        raise ValueError("剪贴板中的二维图元数据无效。") from exc


def instantiate_drawing_clipboard(
    sketch: Sketch, delta: Point2D, *, styles: DimensionStyleTable | None = None
) -> tuple[tuple[SketchEntity, ...], tuple[SketchConstraint, ...]]:
    """Create independent translated entities and rebind their internal constraints."""
    dx, dy = delta
    if not math.isfinite(dx) or not math.isfinite(dy):
        raise ValueError("粘贴位置必须是有限坐标。")
    originals = sketch.entities
    clones = copy_entities(originals, tuple(e.entity_id for e in originals), delta)[
        len(originals) :
    ]
    identities = {old.entity_id: new.entity_id for old, new in zip(originals, clones, strict=True)}

    def translated(point: Point2D | None) -> Point2D | None:
        return None if point is None else (point[0] + dx, point[1] + dy)

    constraints: list[SketchConstraint] = []
    for constraint in sketch.constraints:
        style_name = None
        if constraint.style_name is not None and styles is not None:
            try:
                style = styles.get(constraint.style_name)
            except KeyError:
                pass
            else:
                if (style.precision, style.scale) == (constraint.precision, constraint.scale):
                    style_name = style.name
        constraints.append(
            replace(
                constraint,
                constraint_id=uuid4().hex,
                references=tuple(
                    replace(ref, entity_id=identities[ref.entity_id])
                    for ref in constraint.references
                ),
                position_mm=translated(constraint.position_mm),
                text_position_mm=translated(constraint.text_position_mm),
                style_name=style_name,
            )
        )
    return clones, tuple(constraints)
