# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Supported subset of AutoCAD feature-control-frame content codes.

The codec intentionally rejects cells outside the subset instead of silently
inventing a meaning. External CAD interoperability needs separate validation.
"""

from __future__ import annotations

import re

from mycad.core.geometric_tolerance import DatumReference, ToleranceRow

_CODES = {
    "position": "j",
    "concentricity": "r",
    "symmetry": "i",
    "parallelism": "f",
    "perpendicularity": "b",
    "angularity": "a",
    "cylindricity": "g",
    "flatness": "c",
    "circularity": "e",
    "straightness": "u",
    "surface_profile": "d",
    "line_profile": "k",
    "circular_runout": "h",
    "total_runout": "t",
}
_FROM_CODE = {code: characteristic for characteristic, code in _CODES.items()}
# The command/font name is case-insensitive, but the character after ';'
# selects a font glyph and must not be case-folded into a different symbol.
_TOKEN = re.compile(r"\{\\(?i:Fgdt);([a-z])\}")
_NUMBER = re.compile(r"(?:\d+(?:\.(\d+))?|\.(\d+))")
_LABEL = re.compile(r"[\w-]{1,80}")
_LEGACY_NEGATIVE_ZERO = re.compile(
    r"(?P<prefix>\{\\(?i:Fgdt);n\})?-(?P<zero>0(?:\.0{1,8})?)"
    r"(?P<suffix>\{\\(?i:Fgdt);[ml]\})?"
)


def _symbol(code: str) -> str:
    return "{\\Fgdt;" + code + "}"


def encode_rows(rows: tuple[ToleranceRow, ...], *, allow_hidden: bool = False) -> str:
    """Encode rows; allow_hidden is only for comparing legacy saved metadata."""
    if not rows or len(rows) > 16:
        raise ValueError("DXF tolerance requires 1–16 rows")
    if not allow_hidden and any(row.precision_insufficient for row in rows):
        raise ValueError("形位公差精度不足，非零公差将显示为零")
    return "^J".join(_encode_row(row) for row in rows)


def _encode_row(row: ToleranceRow) -> str:
    if any(not _LABEL.fullmatch(item.label) for item in row.datums):
        raise ValueError("datum label is not supported by DXF codec")
    value = (_symbol("n") if row.diameter else "") + f"{row.value:.{row.precision}f}"
    if row.modifier:
        value += _symbol(row.modifier.lower())
    datums = [
        item.label + (_symbol(item.modifier.lower()) if item.modifier else "")
        for item in row.datums
    ]
    datums.extend([""] * (3 - len(datums)))
    return "%%v".join([_symbol(_CODES[row.characteristic]), value, "", *datums])


def normalize_legacy_negative_zero(content: str) -> str:
    """Normalize old MyCAD negative zero only in the tolerance value cell."""
    rows = re.split(r"(\^J|\r\n|\n)", content, flags=re.IGNORECASE)
    for index in range(0, len(rows), 2):
        cells = re.split(r"(%%v)", rows[index], flags=re.IGNORECASE)
        if len(cells) < 3:
            continue
        match = _LEGACY_NEGATIVE_ZERO.fullmatch(cells[2])
        if match is not None:
            cells[2] = (
                (match.group("prefix") or "") + match.group("zero") + (match.group("suffix") or "")
            )
            rows[index] = "".join(cells)
    return "".join(rows)


def decode_rows(content: str) -> tuple[ToleranceRow, ...]:
    """Decode supported independent rows; references remain unresolved."""
    rows = re.split(r"\^J|\r\n|\n", normalize_legacy_negative_zero(content), flags=re.IGNORECASE)
    if not rows or len(rows) > 16:
        raise ValueError("unsupported tolerance frame row count")
    return tuple(_decode_row(row) for row in rows)


def _decode_row(content: str) -> ToleranceRow:
    cells = re.split("%%v", content, flags=re.IGNORECASE)
    if len(cells) > 6 and not any(cells[6:]):
        cells = cells[:6]
    if not 2 <= len(cells) <= 6:
        raise ValueError("unsupported tolerance frame layout")
    cells.extend([""] * (6 - len(cells)))
    if cells[2] and (not cells[2][0].isalpha() or cells[5]):
        raise ValueError("unsupported second tolerance or datum layout")
    datum_cells = cells[2:5] if cells[2] else cells[3:]
    characteristic = _TOKEN.fullmatch(cells[0])
    if characteristic is None or characteristic.group(1) not in _FROM_CODE:
        raise ValueError("unsupported geometric characteristic")
    text = cells[1]
    prefix = _TOKEN.match(text)
    diameter = prefix is not None and prefix.group(1) == "n"
    if diameter:
        assert prefix is not None
        text = text[prefix.end() :]
    modifier = ""
    suffix = _TOKEN.search(text)
    if suffix is not None and suffix.end() == len(text) and suffix.group(1) in ("m", "l"):
        text = text[: suffix.start()]
        modifier = suffix.group(1).upper()
    match = _NUMBER.fullmatch(text)
    if match is None:
        raise ValueError("unsupported tolerance value")
    precision = len(match.group(1) or match.group(2) or "")
    if precision > 8:
        raise ValueError("unsupported tolerance precision")
    datums: list[DatumReference] = []
    empty_seen = False
    for cell in datum_cells:
        if not cell:
            empty_seen = True
            continue
        if empty_seen:
            raise ValueError("unsupported gap between datum references")
        datum_modifier = ""
        suffix = _TOKEN.search(cell)
        if suffix is not None and suffix.end() == len(cell) and suffix.group(1) in ("m", "l"):
            cell = cell[: suffix.start()]
            datum_modifier = suffix.group(1).upper()
        if not _LABEL.fullmatch(cell):
            raise ValueError("unsupported datum reference")
        datums.append(DatumReference(cell, modifier=datum_modifier))
    return ToleranceRow(
        _FROM_CODE[characteristic.group(1)],
        float(text),
        precision,
        diameter,
        modifier,
        tuple(datums),
    )
