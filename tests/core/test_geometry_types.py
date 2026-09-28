# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral geometry DTO tests."""

from __future__ import annotations

import dataclasses

import pytest

from mycad.core.geometry_types import BoundingBox, MassProperties, Tessellation


def test_bbox_field_lock() -> None:
    fields = {f.name for f in dataclasses.fields(BoundingBox)}
    assert fields == {"xmin", "ymin", "zmin", "xmax", "ymax", "zmax"}


def test_bbox_size_and_center() -> None:
    box = BoundingBox(0.0, 0.0, 0.0, 2.0, 4.0, 6.0)
    assert box.size == (2.0, 4.0, 6.0)
    assert box.center == (1.0, 2.0, 3.0)


def test_bbox_is_frozen() -> None:
    box = BoundingBox(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        box.xmin = 99.0  # type: ignore[misc]


def test_mass_properties_field_lock() -> None:
    fields = {f.name for f in dataclasses.fields(MassProperties)}
    assert fields == {
        "volume",
        "solid_count",
        "cylindrical_face_count",
        "bbox",
        "center_of_mass",
    }


def test_mass_properties_default_center() -> None:
    mp = MassProperties(
        volume=1.0,
        solid_count=1,
        cylindrical_face_count=0,
        bbox=None,
    )
    assert mp.center_of_mass == (0.0, 0.0, 0.0)


def test_tessellation_field_lock() -> None:
    fields = {f.name for f in dataclasses.fields(Tessellation)}
    assert fields == {"vertices", "triangle_indices"}


def test_tessellation_accepts_valid_mesh() -> None:
    verts = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    tri = ((0, 1, 2),)
    tess = Tessellation(verts, tri)
    assert tess.vertices == verts
    assert tess.triangle_indices == tri


def test_tessellation_rejects_out_of_range_index() -> None:
    verts = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    bad = ((0, 1, 5),)
    with pytest.raises(ValueError, match="triangle index out of range"):
        Tessellation(verts, bad)
