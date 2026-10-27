# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Acceptance: extrude the selected face, preserving its holes and source body."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from build123d import Box, Part, Rot

from mycad.app import build_app, new_document, open_app_document
from mycad.core.exceptions import GeometryBuildError, ValidationError
from mycad.core.persistence import save_document
from mycad.geom._b123_features import apply_feature
from mycad.geom.kernel import BuildKernel
from tests.helpers.step_roundtrip import planar_openings


def _flange(kernel: BuildKernel) -> None:
    kernel.apply("feature.cylinder", {"radius": 40.0, "height": 8.0})
    kernel.apply(
        "feature.hole",
        {
            "target_face": {"surface": "plane", "axis": "+Z"},
            "position": {"kind": "center"},
            "diameter": 20.0,
            "depth": {"kind": "through_all"},
        },
    )
    kernel.apply(
        "feature.hole_pattern",
        {
            "base_hole": {
                "target_face": {"surface": "plane", "axis": "+Z"},
                "position": {"kind": "center"},
                "diameter": 6.0,
                "depth": {"kind": "through_all"},
            },
            "pattern": {"kind": "polar", "radius": 25.0, "count": 4},
        },
    )


@pytest.mark.parametrize("axis", ["+Z", "-Z"])
@pytest.mark.parametrize("distance", [3.0, -2.0])
def test_flange_full_face_retains_all_five_holes(
    axis: str, distance: float, tmp_path: Path
) -> None:
    kernel = BuildKernel()
    _flange(kernel)
    kernel.apply(
        "feature.extrude",
        {
            "profile": {"type": "face", "target_face": {"surface": "plane", "axis": axis}},
            "distance": distance,
            "mode": "add" if distance > 0 else "cut",
        },
    )
    props = kernel.mass_properties()
    assert props.solid_count == 1
    assert props.volume == pytest.approx(math.pi * (40**2 - 10**2 - 4 * 3**2) * (8 + distance))
    assert props.bbox is not None
    assert props.bbox.xmax - props.bbox.xmin == pytest.approx(80)
    assert props.bbox.zmax - props.bbox.zmin == pytest.approx(8 + distance)
    # A cylindrical wall may be split at a seam after a boolean. Check actual
    # openings at both ends instead of assuming one BREP face per hole.
    path = tmp_path / "flange.step"
    kernel.export_step(path)
    assert planar_openings(path) == (5, 5)


def test_oblique_face_uses_its_normal_instead_of_global_z() -> None:
    original: Part = Rot(0, 45, 0) * Box(10, 20, 8)
    face = max(original.faces(), key=lambda item: item.normal_at().X + item.normal_at().Z)
    center = face.center()
    result = apply_feature(
        original,
        "feature.extrude",
        {
            "profile": {
                "type": "face",
                "target_face": {
                    "surface": "plane",
                    "center_mm": [center.X, center.Y, center.Z],
                },
            },
            "distance": 3.0,
            "mode": "add",
        },
    )
    assert result is not None
    assert result.volume == pytest.approx(10 * 20 * 11)
    assert len(result.solids()) == 1


def test_face_extrusion_cannot_replace_or_erase_the_original_body() -> None:
    kernel = BuildKernel()
    _flange(kernel)
    before = kernel.mass_properties().volume
    profile = {"type": "face", "target_face": {"surface": "plane", "axis": "+Z"}}
    with pytest.raises(ValidationError, match="不允许替换"):
        kernel.apply("feature.extrude", {"profile": profile, "distance": 3.0, "mode": "new"})
    with pytest.raises(GeometryBuildError, match="删除或分割"):
        kernel.apply("feature.extrude", {"profile": profile, "distance": -20.0, "mode": "cut"})
    assert kernel.mass_properties().volume == pytest.approx(before)


def test_face_extrusion_rejects_symmetric_extent_without_committing() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 20, "size_z": 8}, "test")
    before = services.kernel.mass_properties().volume

    with pytest.raises(ValidationError, match="不支持对称终止"):
        loaded.bus.execute(
            "feature.extrude",
            {
                "profile": {
                    "type": "face",
                    "target_face": {"surface": "plane", "axis": "+Z"},
                },
                "distance": 3.0,
                "mode": "add",
                "extent_mode": "symmetric",
            },
            "test",
        )

    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(before)


def test_face_extrusion_bus_undo_redo_and_archive_replay(tmp_path: Path) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 20, "size_z": 8}, "test")
    loaded.bus.execute(
        "feature.extrude",
        {
            "profile": {"type": "face", "target_face": {"surface": "plane", "axis": "+X"}},
            "distance": 3.0,
            "mode": "add",
        },
        "test",
    )
    assert services.kernel.mass_properties().volume == pytest.approx(13 * 20 * 8)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(10 * 20 * 8)
    loaded.bus.redo()
    path = tmp_path / "face.mc.json"
    save_document(loaded.document, path)
    restored = open_app_document(services, path)
    assert len(restored.document.commands) == 2
    assert services.kernel.mass_properties().volume == pytest.approx(13 * 20 * 8)
