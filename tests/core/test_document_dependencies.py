# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Save ordering is a graph contract, including future nested assemblies."""

import pytest

from mycad.core.exceptions import ValidationError


def test_shared_parts_are_saved_once_before_assemblies_and_drawing() -> None:
    from mycad.core.document_dependencies import save_order

    assert save_order(
        {
            "drawing": ("assembly",),
            "assembly": ("sub", "part"),
            "sub": ("part",),
            "part": ("sketch",),
            "sketch": (),
        }
    ) == ("sketch", "part", "sub", "assembly", "drawing")


def test_cyclic_reference_cannot_be_saved_as_an_ordered_set() -> None:
    from mycad.core.document_dependencies import save_order

    with pytest.raises(ValidationError, match="cycl"):
        save_order({"a": ("b",), "b": ("a",)})
