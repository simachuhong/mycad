# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Geometric symbols do not depend on a system font."""

import pytest

from mycad.core.geometric_tolerance import CHARACTERISTICS
from mycad.ui.geometric_tolerance_symbols import geometric_symbol


@pytest.mark.parametrize("characteristic", CHARACTERISTICS)
def test_all_supported_characteristics_have_visible_vector_symbols(characteristic: str) -> None:
    path = geometric_symbol(characteristic)
    assert path.elementCount() > 1
    bounds = path.boundingRect()
    assert bounds.width() > 0
    assert bounds.left() >= 0 and bounds.right() <= 1
    assert bounds.top() >= 0 and bounds.bottom() <= 1


def test_unknown_symbol_is_rejected() -> None:
    with pytest.raises(ValueError):
        geometric_symbol("unknown")
