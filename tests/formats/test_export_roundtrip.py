# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Golden flange export end-to-end (T8b): real geometry through the registry.

The flange is the T11 happy-path command sequence (cylinder + center hole
+ 4x polar hole pattern) applied straight to a BuildKernel — no
composition-root symbols, no document history (export is a read-only,
off-bus service).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from mycad.core.exceptions import (
    EmptyGeometryError,
    ProviderConflictError,
    UnknownFormatError,
)
from mycad.formats import (
    STEP_PROVIDER,
    STL_PROVIDER,
    FormatProvider,
    FormatProviderRegistry,
)
from mycad.geom.kernel import BuildKernel
from tests.helpers.step_roundtrip import read_step

# math.pi * 8 * (40^2 - 10^2 - 4 * 3^2): R40x8 disc, D20 center bore,
# 4 x D6 through holes on a 25mm bolt circle.
EXPECTED_FLANGE_VOLUME_MM3 = math.pi * 8.0 * (40.0**2 - 10.0**2 - 4 * 3.0**2)
VOLUME_TOLERANCE = 1e-6

FLANGE_CENTER_HOLE: Mapping[str, object] = {
    "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
    "position": {"kind": "center"},
    "diameter": 20.0,
    "depth": {"kind": "through_all"},
}
FLANGE_COMMANDS: Sequence[tuple[str, Mapping[str, object]]] = (
    (
        "feature.cylinder",
        {"radius": 40.0, "height": 8.0, "center": [0.0, 0.0, 0.0], "mode": "new"},
    ),
    ("feature.hole", FLANGE_CENTER_HOLE),
    (
        "feature.hole_pattern",
        {
            "base_hole": {**FLANGE_CENTER_HOLE, "diameter": 6.0},
            "pattern": {
                "kind": "polar",
                "radius": 25.0,
                "count": 4,
                "start_angle_deg": 0.0,
            },
        },
    ),
)


@pytest.fixture()
def flange_kernel() -> BuildKernel:
    """Golden flange: T11 parameters, asserted golden BEFORE any export."""

    kernel = BuildKernel()
    for command_id, params in FLANGE_COMMANDS:
        kernel.apply(command_id, params)
    mp = kernel.mass_properties()
    assert abs(mp.volume - EXPECTED_FLANGE_VOLUME_MM3) < VOLUME_TOLERANCE
    assert mp.solid_count == 1
    return kernel


def _registry() -> FormatProviderRegistry:
    return FormatProviderRegistry([STEP_PROVIDER, STL_PROVIDER])


def test_flange_step_roundtrip(flange_kernel: BuildKernel, tmp_path: Path) -> None:
    path = tmp_path / "flange.step"
    port = _registry().resolve(path)
    port.write(flange_kernel, path)
    assert path.stat().st_size > 10240
    solids, volume = read_step(path)
    assert solids == 1
    assert abs(volume - EXPECTED_FLANGE_VOLUME_MM3) < VOLUME_TOLERANCE


def test_flange_stl_export(flange_kernel: BuildKernel, tmp_path: Path) -> None:
    path = tmp_path / "flange.stl"
    port = _registry().resolve(path)
    port.write(flange_kernel, path)
    assert path.stat().st_size > 1024


def test_chinese_path(flange_kernel: BuildKernel, tmp_path: Path) -> None:
    """Non-ASCII directory + filename: write and read back losslessly."""

    directory = tmp_path / "目录"
    directory.mkdir(parents=True)
    path = directory / "flange_法兰.step"
    port = _registry().resolve(path)
    port.write(flange_kernel, path)
    solids, volume = read_step(path)
    assert solids == 1
    assert abs(volume - EXPECTED_FLANGE_VOLUME_MM3) < VOLUME_TOLERANCE


@pytest.mark.parametrize("suffix", [".x_t", ".dwg"])
def test_unknown_format_rejected(suffix: str, tmp_path: Path) -> None:
    path = tmp_path / f"part{suffix}"
    with pytest.raises(UnknownFormatError) as excinfo:
        _registry().resolve(path)
    assert "support" not in str(excinfo.value).lower()


@pytest.mark.parametrize("suffix", [".step", ".stl"])
def test_empty_export_rejected(suffix: str, tmp_path: Path) -> None:
    path = tmp_path / f"empty{suffix}"
    port = _registry().resolve(path)
    with pytest.raises(EmptyGeometryError):
        port.write(BuildKernel(), path)
    assert not path.exists()


def test_same_priority_conflict(tmp_path: Path) -> None:
    def _noop(geometry: object, path: Path) -> None:
        return None

    first = FormatProvider(
        name="Alpha",
        vendor="VendorA",
        priority=100,
        extensions=(".step",),
        can_read=False,
        can_write=True,
        target="shape",
        _writer=_noop,
    )
    second = FormatProvider(
        name="Beta",
        vendor="VendorB",
        priority=100,
        extensions=(".step",),
        can_read=False,
        can_write=True,
        target="shape",
        _writer=_noop,
    )
    with pytest.raises(ProviderConflictError) as excinfo:
        FormatProviderRegistry([first, second])
    assert excinfo.value.extension == ".step"
    assert excinfo.value.provider1 == ("Alpha", "VendorA")
    assert excinfo.value.provider2 == ("Beta", "VendorB")
