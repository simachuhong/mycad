# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Round datum symbols preserve their style as structured annotation data."""

import pytest

from mycad.core.geometric_tolerance import DatumIdentifier


def test_round_datum_style_roundtrips_and_old_records_remain_rectangular() -> None:
    original = DatumIdentifier("a" * 32, "A", (0, 10), (0, 0), symbol_style="circle")
    record = original.to_mapping()
    assert record["symbol_style"] == "circle"
    assert DatumIdentifier.from_mapping(record) == original
    old = DatumIdentifier("b" * 32, "B", (0, 10), (0, 0))
    assert "symbol_style" not in old.to_mapping()
    assert DatumIdentifier.from_mapping(old.to_mapping()).symbol_style == "rectangle"


def test_unknown_datum_symbol_style_is_rejected() -> None:
    with pytest.raises(ValueError, match="symbol style"):
        DatumIdentifier("a" * 32, "A", (0, 10), (0, 0), symbol_style="unknown")


def test_bar_direction_is_preserved_in_structured_record() -> None:
    datum = DatumIdentifier(
        "c" * 32, "A", (0, 10), (0, 0), symbol_style="circle", bar_direction=(2, 0)
    )
    assert datum.bar_direction == (1, 0)
    assert DatumIdentifier.from_mapping(datum.to_mapping()) == datum
    with pytest.raises(ValueError, match="direction"):
        DatumIdentifier("d" * 32, "A", (0, 10), (0, 0), symbol_style="circle", bar_direction=(0, 0))
