# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Contract tests for the ViewportData protocol (phase 1, todo 2).

The port is the third core-side dependency inversion: an empty document
vacuously satisfies ``ViewportPort``, bad triangles must die at
construction time (Tessellation's own ``__post_init__``), and the DTO
must be frozen so preview data cannot be mutated mid-frame.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from mycad.core.geometry_types import Tessellation
from mycad.core.viewport_protocol import ViewportData, ViewportPort


class _EmptyKernelPort:
    def viewport_data(self) -> tuple[ViewportData, ...]:
        return ()


def test_viewport_port_is_runtime_checkable_and_allows_empty() -> None:
    """One snapshot per ordinal; an empty document yields an empty tuple."""
    port = _EmptyKernelPort()
    assert isinstance(port, ViewportPort)
    assert port.viewport_data() == ()
    assert isinstance(port.viewport_data(), tuple)


def test_indices_validation_red_path() -> None:
    """A mesh with an out-of-range index must fail at construction, not
    at render time — ViewportData inherits Tessellation's validation."""
    with pytest.raises(ValueError, match="triangle index out of range"):
        ViewportData(
            feature_id="demo.cylinder:1",
            mesh=Tessellation(vertices=((0.0, 0.0, 0.0),), triangle_indices=((0, 1, 2),)),
        )


def test_frozen_immutable() -> None:
    data = ViewportData(
        feature_id="demo.cylinder:1",
        mesh=Tessellation(vertices=((0.0, 0.0, 0.0),), triangle_indices=()),
        normals=((0.0, 0.0, 1.0),),
    )
    # setattr via a variable name: a direct assignment is a static error on
    # a frozen dataclass, and the repo allows no suppression comments here
    # (same convention as tests/core/test_geometry_types.py).
    field_name = "feature_id"
    with pytest.raises(FrozenInstanceError):
        setattr(data, field_name, "demo.hole_pattern:2")
