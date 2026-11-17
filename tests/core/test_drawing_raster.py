# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral, replayable drawing raster data."""

import base64
import struct
import zlib
from uuid import uuid4

import pytest

from mycad.core.drawing_raster import DrawingRaster


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )


def _mapping() -> dict[str, object]:
    return {
        "image_id": uuid4().hex,
        "png_base64": base64.b64encode(_png()).decode("ascii"),
        "origin_mm": [2, 3],
        "width_mm": 20,
        "height_mm": 10,
        "layer_name": "0",
    }


def test_raster_roundtrip_preserves_pixels_and_placement() -> None:
    data = _mapping()
    image = DrawingRaster.from_mapping(data)
    assert image.to_mapping() == data
    assert image.pixel_size == (1, 1)
    assert image.png_bytes == _png()


@pytest.mark.parametrize(
    "field,value",
    [
        ("width_mm", 0),
        ("height_mm", -1),
        ("width_mm", float("inf")),
        ("origin_mm", [1, float("nan")]),
    ],
)
def test_raster_rejects_invalid_placement(field: str, value: object) -> None:
    data = _mapping()
    data[field] = value
    with pytest.raises(ValueError):
        DrawingRaster.from_mapping(data)


@pytest.mark.parametrize(
    "value",
    [
        "invalid base64!",
        base64.b64encode(b"not png").decode(),
        base64.b64encode(_png()[:-5]).decode(),
    ],
)
def test_raster_rejects_invalid_png(value: str) -> None:
    data = _mapping()
    data["png_base64"] = value
    with pytest.raises(ValueError):
        DrawingRaster.from_mapping(data)
