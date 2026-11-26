# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF feature control frame codes retain structured supported cells."""

import pytest

from mycad.core.geometric_tolerance import DatumReference, ToleranceRow
from mycad.formats.geometric_tolerance_codec import decode_rows, encode_rows


def test_incompressible_frame_metadata_cannot_exceed_xdata_budget() -> None:
    import random
    import string

    from mycad.formats.dxf_xdata import pack_annotation_metadata

    randomizer = random.Random(42)
    payload = "".join(
        randomizer.choices(string.ascii_letters + string.digits + string.punctuation, k=20000)
    )
    with pytest.raises(ValueError, match="扩展数据"):
        pack_annotation_metadata(payload)


def test_single_row_uses_autodesk_feature_frame_codes() -> None:
    rows = (
        ToleranceRow(
            "position", 0.05, 2, True, "M", (DatumReference("A"), DatumReference("B", modifier="L"))
        ),
    )
    encoded = encode_rows(rows)
    assert encoded == r"{\Fgdt;j}%%v{\Fgdt;n}0.05{\Fgdt;m}%%v%%vA%%vB{\Fgdt;l}%%v"
    assert decode_rows(encoded) == rows


def test_nonzero_frame_tolerance_cannot_be_encoded_as_zero() -> None:
    with pytest.raises(ValueError, match="精度"):
        encode_rows((ToleranceRow("flatness", 1e-10, 2),))
    assert "0.00" in encode_rows((ToleranceRow("flatness", 0, 2),))


def test_negative_zero_tolerance_encodes_as_readable_zero() -> None:
    row = ToleranceRow("flatness", -0.0, 2)
    encoded = encode_rows((row,))
    assert "-0.00" not in encoded
    assert decode_rows(encoded) == (row,)


def test_legacy_negative_zero_decodes_but_negative_value_does_not() -> None:
    assert decode_rows(r"{\Fgdt;j}%%v{\Fgdt;n}-0.00{\Fgdt;m}%%v%%vA") == (
        ToleranceRow("position", 0, 2, True, "M", (DatumReference("A"),)),
    )
    with pytest.raises(ValueError):
        decode_rows(r"{\Fgdt;j}%%v-0.01%%v%%vA")


def test_legacy_zero_normalization_does_not_alter_datum_label() -> None:
    from mycad.formats.geometric_tolerance_codec import normalize_legacy_negative_zero

    content = r"{\Fgdt;j}%%v-0.00%%v%%v-0%%v%%v"
    assert normalize_legacy_negative_zero(content) == r"{\Fgdt;j}%%v0.00%%v%%v-0%%v%%v"
    assert decode_rows(content)[0].datums == (DatumReference("-0"),)


def test_unknown_content_is_not_silently_dropped() -> None:
    with pytest.raises(ValueError):
        decode_rows(r"{\Fgdt;x}%%v0.1%%v%%vA%%v%%v")


@pytest.mark.parametrize("value,precision", [(".05", 2), (".5000", 4), (".0", 1)])
def test_external_value_can_suppress_leading_zero(value: str, precision: int) -> None:
    rows = decode_rows(r"{\Fgdt;j}%%v" + value + "%%v%%vA")
    assert rows == (
        ToleranceRow("position", float(value), precision, datums=(DatumReference("A"),)),
    )


@pytest.mark.parametrize("value", [".", "-.05", ".1.2", ".000000001"])
def test_invalid_leading_zero_suppressed_values_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        decode_rows(r"{\Fgdt;j}%%v" + value)


def test_missing_datum_cell_is_not_collapsed() -> None:
    with pytest.raises(ValueError):
        decode_rows(r"{\Fgdt;j}%%v0.1%%v%%vA%%v%%vC")


def test_multiline_independent_rows_roundtrip() -> None:
    rows = (
        ToleranceRow("position", 0.05, 2, True, "M", (DatumReference("A"),)),
        ToleranceRow("flatness", 0.1, 1),
    )
    text = encode_rows(rows)
    assert "^J" in text
    assert decode_rows(text) == rows


def test_autocad_community_two_row_text_with_crlf_decodes() -> None:
    # Autodesk Community 2018 accepted solution uses vbCrLf between these cells.
    first = r"{\Fgdt;j}%%v{\Fgdt;n}0.1{\Fgdt;m}%%v%%vC%%vA%%vB"
    second = r"{\Fgdt;j}%%v{\Fgdt;n}0.2{\Fgdt;m}%%v%%vC%%v%%v"
    assert decode_rows(first + "\r\n" + second) == (
        ToleranceRow(
            "position",
            0.1,
            1,
            True,
            "M",
            (DatumReference("C"), DatumReference("A"), DatumReference("B")),
        ),
        ToleranceRow("position", 0.2, 1, True, "M", (DatumReference("C"),)),
    )


def test_unicode_datum_labels_roundtrip_without_interpreting_control_codes() -> None:
    rows = (
        ToleranceRow(
            "position",
            0.1,
            1,
            datums=(DatumReference("基准甲"), DatumReference("測定_B", modifier="M")),
        ),
    )
    assert decode_rows(encode_rows(rows)) == rows
    for unsafe in ("A%%vB", "A^JB", r"A\B", "A B"):
        with pytest.raises(ValueError):
            encode_rows((ToleranceRow("position", 0.1, 1, datums=(DatumReference(unsafe),)),))


def test_decodes_external_cad_sample_with_early_datum_cell() -> None:
    # LibreDWG issue #1187 includes an AC1014 TOLERANCE entity from a DWG sample.
    from mycad.core.geometric_tolerance import DatumReference, ToleranceRow
    from mycad.formats.geometric_tolerance_codec import decode_rows

    rows = decode_rows(r"{\Fgdt;r}%%v0.08%%vA%%v%%v%%v")
    assert rows == (ToleranceRow("concentricity", 0.08, 2, datums=(DatumReference("A"),)),)


def test_fcf_gdt_font_name_case_may_vary_but_glyph_case_is_significant() -> None:
    text = r"{\fGDT;j}%%V{\FGDT;n}0.05{\fgdt;m}%%V%%VA{\fGdt;l}%%V%%V"
    assert decode_rows(text) == (
        ToleranceRow("position", 0.05, 2, True, "M", (DatumReference("A", modifier="L"),)),
    )


@pytest.mark.parametrize(
    "text",
    (
        r"{\Fgdt;J}%%v0.1%%v%%vA%%v%%v",
        r"{\Fgdt;j}%%v{\Fgdt;N}0.1%%v%%vA%%v%%v",
        r"{\Fgdt;j}%%v0.1{\Fgdt;M}%%v%%vA%%v%%v",
        r"{\Fgdt;j}%%v0.1%%v%%vA{\Fgdt;L}%%v%%v",
    ),
)
def test_unknown_uppercase_gdt_glyph_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        decode_rows(text)


@pytest.mark.parametrize(
    ("content", "expected"),
    (
        (r"{\Fgdt;j}%%v{\Fgdt;n}0.7{\Fgdt;m}", ToleranceRow("position", 0.7, 1, True, "M")),
        (
            r"{\Fgdt;j}%%v0.1%%v%%vA%%vB",
            ToleranceRow("position", 0.1, 1, datums=(DatumReference("A"), DatumReference("B"))),
        ),
        (
            r"{\Fgdt;j}%%v0.1%%vA%%vB",
            ToleranceRow("position", 0.1, 1, datums=(DatumReference("A"), DatumReference("B"))),
        ),
    ),
)
def test_external_tolerance_may_omit_trailing_empty_cells(
    content: str, expected: ToleranceRow
) -> None:
    assert decode_rows(content) == (expected,)


def test_short_external_format_rejects_ambiguous_second_tolerance() -> None:
    with pytest.raises(ValueError):
        decode_rows(r"{\Fgdt;j}%%v0.1%%v0.2")


def test_external_tolerance_accepts_redundant_empty_trailing_cells() -> None:
    text = r"{\Fgdt;j}%%v0.1%%v%%vA%%vB%%vC%%v%%v"
    assert decode_rows(text) == (
        ToleranceRow(
            "position",
            0.1,
            1,
            datums=(DatumReference("A"), DatumReference("B"), DatumReference("C")),
        ),
    )


def test_external_tolerance_rejects_nonempty_extra_cell() -> None:
    with pytest.raises(ValueError):
        decode_rows(r"{\Fgdt;j}%%v0.1%%v%%vA%%vB%%vC%%vEXTRA")
