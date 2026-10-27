# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drawing layout is not a new BREP result or a new topology generation."""

from uuid import uuid4

from mycad.app import build_app, new_document


def test_layout_command_keeps_geometry_identity() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    kernel = services.kernel
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    before = kernel.viewport_data()[0]
    feature = kernel.current_feature_id
    bodies = kernel.body_ids
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)}, "test")
    after = kernel.viewport_data()[0]
    assert after.geometry_revision == before.geometry_revision
    assert after.mesh is before.mesh
    assert after.faces == before.faces
    assert after.body_origins == before.body_origins
    assert kernel.current_feature_id == feature
    assert kernel.body_ids == bodies
    assert after.state_id == "drawing.sheet.create:1"
    assert len(kernel.viewport_state_ids()) == 2
    loaded.bus.execute("drawing.sheet.update", {"sheet_id": str(sheet), "name": "工件图"}, "test")
    assert kernel.drawing_revision == 2
    assert kernel.drawing_state.sheet(sheet).name == "工件图"
    kernel.reset()
    assert not kernel.drawing_state.sheets
