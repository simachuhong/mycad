# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""T0 existing non-geometric history and v3 parameter-envelope characterization."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from mycad.app import build_app, new_document, open_app_document
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.schema_v3 import validate_archive_v3
from mycad.core.sketch import Sketch, WorkPlaneFrame


def test_non_geometry_history_preserves_body_source_through_replay_and_open(tmp_path: Path) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    kernel = services.kernel
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    before = kernel.viewport_data()[-1]
    loaded.bus.execute(
        "drawing.layers.set",
        {
            "layers": kernel.drawing_layers.to_mapping(),
            "dimension_layer": "DIM",
        },
        "test",
    )
    after = kernel.viewport_data()[-1]
    assert after.body_origins[0].result == before.body_origins[0].result
    assert kernel.mass_properties().volume == pytest.approx(6400)
    assert len(kernel.viewport_state_ids()) == 2
    assert after.state_id == "drawing.layers.set:1"
    loaded.bus.undo()
    assert len(kernel.viewport_state_ids()) == 1
    loaded.bus.redo()
    assert kernel.viewport_data()[-1].body_origins[0].result == before.body_origins[0].result
    path = tmp_path / "history.my3d"
    save_document(loaded.document, path)
    open_app_document(services, path)
    assert kernel.viewport_data()[-1].body_origins[0].result == before.body_origins[0].result
    assert len(kernel.viewport_state_ids()) == 2
    # Current layer changes DO increment geometry revision. T2 must use a separate
    # drawing-only checkpoint path rather than copying _record_sketch_change.
    assert after.geometry_revision > before.geometry_revision


def test_v3_can_store_new_command_parameters_without_new_top_level_fields(tmp_path: Path) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="part")
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "test")
    path = tmp_path / "source.my3d"
    save_document(loaded.document, path)
    archive = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    archive["version"] = 3
    archive["document_type"] = "part"
    commands = cast("list[dict[str, object]]", archive["commands"])
    first_audit = deepcopy(commands[0])
    commands.append(
        {
            "id": "drawing.view.create",
            "version": 1,
            "params": {
                "view_id": "probe-view",
                "sheet_id": "probe-sheet",
                "source": {"kind": "current_part"},
                "scale": 0.5,
                "basis": {"right": [1, 0, 0], "up": [0, 0, 1], "normal": [0, -1, 0]},
            },
            "ordinal": 2,
            "timestamp_utc": "2026-10-27T00:00:00+00:00",
            "confirmed_by": "test",
        }
    )
    validate_archive_v3(archive)
    assert commands[0] == first_audit
    # Schema acceptance is not command registration/execution support.
    archive["document_type"] = "drawing2d"
    with pytest.raises(ValidationError, match="drawing2d"):
        validate_archive_v3(archive)
