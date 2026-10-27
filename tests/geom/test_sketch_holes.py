# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A sketch of circles drives checked blind and through-hole features."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from mycad.app import build_app, new_document
from mycad.core.sketch import CircleEntity, RectangleEntity, Sketch, WorkPlaneFrame
from tests.helpers.step_roundtrip import read_step

SKETCH_ID = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
HOLE_A_ID = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
HOLE_B_ID = "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c"


def _plate_document():
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute(
        "feature.box",
        {"size_x": 20.0, "size_y": 20.0, "size_z": 10.0},
        confirmed_by="local",
    )
    sketch = Sketch(
        sketch_id=SKETCH_ID,
        frame=WorkPlaneFrame(
            origin_mm=(0.0, 0.0, 5.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
            normal=(0.0, 0.0, 1.0),
        ),
        entities=(
            CircleEntity(HOLE_A_ID, (-5.0, 0.0), 2.0),
            CircleEntity(HOLE_B_ID, (5.0, 0.0), 3.0),
        ),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    return services, loaded


def _hole_params(depth: dict[str, object]) -> dict[str, object]:
    return {
        "profile": {"type": "sketch", "sketch_id": SKETCH_ID},
        "target_face": {"surface": "plane", "axis": "+Z"},
        "depth": depth,
    }


def test_sketch_holes_replay_and_cut_two_circle_sizes_through_all() -> None:
    services, loaded = _plate_document()

    loaded.bus.execute("feature.hole", _hole_params({"kind": "through_all"}), "local", version=2)

    expected = 20.0 * 20.0 * 10.0 - math.pi * (2.0**2 + 3.0**2) * 10.0
    assert loaded.document.commands[-1].version == 2
    assert services.kernel.mass_properties().volume == pytest.approx(expected, rel=2e-5)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(4000.0)
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(expected, rel=2e-5)


def test_sketch_hole_blind_depth_is_measured_in_millimetres() -> None:
    services, loaded = _plate_document()

    loaded.bus.execute(
        "feature.hole", _hole_params({"kind": "blind", "value": 4.0}), "local", version=2
    )

    expected = 4000.0 - math.pi * (2.0**2 + 3.0**2) * 4.0
    assert services.kernel.mass_properties().volume == pytest.approx(expected, rel=2e-5)


def test_hole_v2_still_accepts_the_legacy_face_parameter_shape() -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute(
        "feature.box",
        {"size_x": 20.0, "size_y": 20.0, "size_z": 10.0},
        confirmed_by="local",
    )

    loaded.bus.execute(
        "feature.hole",
        {
            "target_face": {"surface": "plane", "axis": "+Z"},
            "position": {"kind": "center"},
            "diameter": 4.0,
            "depth": {"kind": "through_all"},
        },
        confirmed_by="local",
        version=2,
    )

    assert loaded.document.commands[-1].version == 2
    assert services.kernel.mass_properties().volume == pytest.approx(4000.0 - math.pi * 2**2 * 10)


def test_sketch_plate_with_four_sketch_holes_exports_the_same_step_volume(
    tmp_path: Path,
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    plate_sketch_id = "3d3d3d3d-3d3d-4d3d-8d3d-3d3d3d3d3d3d"
    hole_sketch_id = "4e4e4e4e-4e4e-4e4e-8e4e-4e4e4e4e4e4e"
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            plate_sketch_id,
            WorkPlaneFrame.xy(),
            (
                RectangleEntity(
                    "5f5f5f5f-5f5f-4f5f-8f5f-5f5f5f5f5f5f", (-10.0, -10.0), (10.0, 10.0)
                ),
            ),
        ).to_mapping(),
        confirmed_by="local",
    )
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            hole_sketch_id,
            WorkPlaneFrame(
                origin_mm=(0.0, 0.0, 8.0),
                u_axis=(1.0, 0.0, 0.0),
                v_axis=(0.0, 1.0, 0.0),
                normal=(0.0, 0.0, 1.0),
            ),
            tuple(
                CircleEntity(entity_id, center, 1.0)
                for entity_id, center in zip(
                    (
                        "6a6a6a6a-6a6a-4a6a-8a6a-6a6a6a6a6a6a",
                        "7b7b7b7b-7b7b-4b7b-8b7b-7b7b7b7b7b7b",
                        "8c8c8c8c-8c8c-4c8c-8c8c-8c8c8c8c8c8c",
                        "9d9d9d9d-9d9d-4d9d-8d9d-9d9d9d9d9d9d",
                    ),
                    ((-5.0, -5.0), (5.0, -5.0), (-5.0, 5.0), (5.0, 5.0)),
                    strict=True,
                )
            ),
        ).to_mapping(),
        confirmed_by="local",
    )
    loaded.bus.execute(
        "feature.extrude",
        {
            "profile": {"type": "sketch", "sketch_id": plate_sketch_id},
            "distance": 8.0,
            "mode": "new",
        },
        confirmed_by="local",
        version=2,
    )
    loaded.bus.execute(
        "feature.hole",
        {
            "profile": {"type": "sketch", "sketch_id": hole_sketch_id},
            "target_face": {"surface": "plane", "axis": "+Z"},
            "depth": {"kind": "through_all"},
        },
        confirmed_by="local",
        version=2,
    )

    expected_volume = 20.0 * 20.0 * 8.0 - 4.0 * math.pi * 8.0
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=2e-5)
    step_path = tmp_path / "four-hole-plate.step"
    services.kernel.export_step(step_path)
    assert read_step(step_path) == pytest.approx((1, expected_volume), rel=2e-5)
