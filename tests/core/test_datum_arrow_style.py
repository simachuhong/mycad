# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Datum pointer style is a versioned, round-trippable property."""

from dataclasses import replace

import pytest

from mycad.core.geometric_tolerance import DatumIdentifier


@pytest.mark.parametrize("style", ["filled", "open", "none"])
def test_datum_arrow_style_roundtrips(style: str) -> None:
    datum = DatumIdentifier("8" * 32, "A", (10, 10), (0, 0), arrow_style=style)
    assert DatumIdentifier.from_mapping(datum.to_mapping()) == datum


def test_legacy_datum_defaults_to_filled_and_rejects_unknown_arrow_style() -> None:
    old = DatumIdentifier("8" * 32, "A", (10, 10), (0, 0))
    assert old.arrow_style == "filled" and "arrow_style" not in old.to_mapping()
    with pytest.raises(ValueError):
        replace(old, arrow_style="unsupported")
