# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Body identity follows live bodies, not every feature snapshot."""

from __future__ import annotations

from mycad.app import build_app, new_document


def test_body_identity_persists_within_one_body_but_not_across_replay() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0}, "test")
    original_body = services.kernel.body_ids[0]
    loaded.bus.execute(
        "feature.box",
        {
            "size_x": 4.0,
            "size_y": 4.0,
            "size_z": 4.0,
            "center": [0.0, 0.0, 0.0],
            "mode": "add",
        },
        "test",
    )

    assert len(services.kernel.feature_ids) == 2
    assert services.kernel.body_ids == (original_body,)

    loaded.bus.undo()
    after_undo = services.kernel.body_ids[0]
    loaded.bus.redo()
    after_redo = services.kernel.body_ids[0]

    assert after_undo != original_body
    assert after_redo != original_body
    assert after_redo != after_undo


def test_disconnected_solids_receive_distinct_current_body_ids() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0}, "test")
    loaded.bus.execute(
        "feature.box",
        {
            "size_x": 4.0,
            "size_y": 4.0,
            "size_z": 4.0,
            "center": [20.0, 0.0, 0.0],
            "mode": "add",
        },
        "test",
    )

    assert services.kernel.geometry_check().solid_count == 2
    assert len(services.kernel.body_ids) == 2
    assert services.kernel.body_ids[0] != services.kernel.body_ids[1]
