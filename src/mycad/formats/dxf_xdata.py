# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bounded, backward-compatible XDATA packing for annotation metadata."""

from __future__ import annotations

import base64
import zlib

_XDATA_BUDGET = 14 * 1024
_MAX_METADATA = 1024 * 1024


def pack_annotation_metadata(payload: str) -> tuple[str, ...]:
    """Pack ASCII JSON under a conservative per-entity XDATA budget."""
    if not payload.isascii() or len(payload) > _MAX_METADATA:
        raise ValueError("标注元数据格式无效或过大")

    def chunks(value: str) -> tuple[str, ...]:
        return tuple(value[index : index + 240] for index in range(0, len(value), 240))

    parts = chunks(payload)
    if sum(len(part.encode("utf-8")) + 4 for part in parts) > _XDATA_BUDGET:
        compressed = base64.b64encode(zlib.compress(payload.encode("utf-8"))).decode("ascii")
        parts = ("Z1", *chunks(compressed))
    if sum(len(part.encode("utf-8")) + 4 for part in parts) > _XDATA_BUDGET:
        raise ValueError("标注元数据超过 DXF 扩展数据大小限制")
    return parts


def unpack_annotation_metadata(parts: tuple[str, ...]) -> str:
    """Read legacy JSON or bounded compressed annotation metadata."""
    if not parts or parts[0] != "Z1":
        return "".join(parts)
    try:
        compressed = base64.b64decode("".join(parts[1:]), validate=True)
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(compressed, _MAX_METADATA + 1)
        if len(decoded) > _MAX_METADATA or not decoder.eof or decoder.unused_data:
            raise ValueError("压缩元数据无效或过大")
        return decoded.decode("utf-8")
    except (ValueError, zlib.error, UnicodeDecodeError) as exc:
        raise ValueError("压缩元数据无效或过大") from exc
