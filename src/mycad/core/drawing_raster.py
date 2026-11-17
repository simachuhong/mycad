# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Backend-neutral, bounded raster reference data for 2D drawings."""

from __future__ import annotations

import base64
import binascii
import math
import struct
import zlib
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from mycad.core.sketch_layers import SketchLayer

MAX_RASTER_BYTES = 12_000_000
MAX_RASTER_PIXELS = 25_000_000
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_size(data: bytes) -> tuple[int, int]:
    if len(data) > MAX_RASTER_BYTES or not data.startswith(_PNG_SIGNATURE):
        raise ValueError("图片必须是大小受限的 PNG。")
    offset = len(_PNG_SIGNATURE)
    size: tuple[int, int] | None = None
    seen_data = False
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("PNG 数据不完整。")
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(kind + payload) != expected_crc:
            raise ValueError("PNG 数据校验失败。")
        if size is None:
            if kind != b"IHDR" or length != 13:
                raise ValueError("PNG 缺少有效头部。")
            width, height = struct.unpack_from(">II", payload)
            if width == 0 or height == 0 or width * height > MAX_RASTER_PIXELS:
                raise ValueError("图片像素数量超出限制。")
            size = (width, height)
        elif kind == b"IHDR":
            raise ValueError("PNG 头部重复。")
        elif kind == b"IDAT":
            seen_data = True
        elif kind == b"IEND":
            if length != 0 or not seen_data or end != len(data):
                raise ValueError("PNG 数据不完整。")
            return size
        offset = end
    raise ValueError("PNG 数据不完整。")


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name}必须是有限数值。")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name}必须是有限数值。") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name}必须是有限数值。")
    return result


@dataclass(frozen=True, slots=True)
class DrawingRaster:
    """An embedded PNG with a local frame in drawing millimetres."""

    image_id: str
    png_base64: str
    origin_mm: tuple[float, float]
    width_mm: float
    height_mm: float
    layer_name: str = "0"
    angle_deg: float = 0.0
    mirrored: bool = False

    def __post_init__(self) -> None:
        try:
            parsed = UUID(self.image_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("图片身份无效。") from exc
        if self.image_id not in (parsed.hex, str(parsed)):
            raise ValueError("图片身份无效。")
        if (
            not isinstance(cast("object", self.png_base64), str)
            or len(self.png_base64) > (MAX_RASTER_BYTES + 2) // 3 * 4
        ):
            raise ValueError("图片数据超出限制。")
        try:
            data = base64.b64decode(self.png_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("图片数据编码无效。") from exc
        if base64.b64encode(data).decode("ascii") != self.png_base64:
            raise ValueError("图片数据编码无效。")
        _png_size(data)
        if not isinstance(cast("object", self.origin_mm), tuple | list) or len(self.origin_mm) != 2:
            raise ValueError("图片位置无效。")
        origin = (_finite(self.origin_mm[0], "图片位置"), _finite(self.origin_mm[1], "图片位置"))
        width, height = _finite(self.width_mm, "图片宽度"), _finite(self.height_mm, "图片高度")
        if width <= 0 or height <= 0:
            raise ValueError("图片宽度和高度必须为正数。")
        object.__setattr__(self, "origin_mm", origin)
        object.__setattr__(self, "width_mm", width)
        object.__setattr__(self, "height_mm", height)
        object.__setattr__(self, "layer_name", SketchLayer(self.layer_name).name)
        object.__setattr__(self, "angle_deg", _finite(self.angle_deg, "图片旋转角"))
        if not isinstance(cast("object", self.mirrored), bool):
            raise ValueError("图片镜像状态无效。")

    @property
    def png_bytes(self) -> bytes:
        return base64.b64decode(self.png_base64, validate=True)

    @property
    def pixel_size(self) -> tuple[int, int]:
        return _png_size(self.png_bytes)

    def to_mapping(self, *, version: int = 1) -> dict[str, object]:
        result: dict[str, object] = {
            "image_id": self.image_id,
            "png_base64": self.png_base64,
            "origin_mm": list(self.origin_mm),
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "layer_name": self.layer_name,
        }
        if version >= 2:
            result.update(angle_deg=self.angle_deg, mirrored=self.mirrored)
        return result

    @classmethod
    def from_mapping(cls, value: object) -> DrawingRaster:
        if not isinstance(value, dict):
            raise ValueError("图片数据格式无效。")
        data = cast("dict[str, object]", value)
        fields = {
            "image_id",
            "png_base64",
            "origin_mm",
            "width_mm",
            "height_mm",
            "layer_name",
        }
        if set(data) not in (fields, fields | {"angle_deg", "mirrored"}):
            raise ValueError("图片数据字段无效。")
        origin = data["origin_mm"]
        if not isinstance(origin, list | tuple):
            raise ValueError("图片位置无效。")
        points = cast("tuple[object, ...] | list[object]", origin)
        if len(points) != 2:
            raise ValueError("图片位置无效。")
        return cls(
            cast("str", data["image_id"]),
            cast("str", data["png_base64"]),
            (_finite(points[0], "图片位置"), _finite(points[1], "图片位置")),
            _finite(data["width_mm"], "图片宽度"),
            _finite(data["height_mm"], "图片高度"),
            cast("str", data["layer_name"]),
            _finite(data.get("angle_deg", 0.0), "图片旋转角"),
            cast("bool", data.get("mirrored", False)),
        )
