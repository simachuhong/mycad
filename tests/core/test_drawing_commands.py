# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drawing command groups are atomic and one user action is one undo."""

from uuid import uuid4

import pytest

from mycad.app import build_app, new_document
from mycad.core.exceptions import MycadError


def test_group_creation_is_atomic_and_replayable() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    sheet, base, child = (uuid4() for _ in range(3))
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)}, "test")
    params = {
        "views": [
            {"view_id": str(base), "sheet_id": str(sheet)},
            {
                "view_id": str(child),
                "sheet_id": str(sheet),
                "parent_id": str(base),
                "direction": "top",
                "offset_mm": [0, -50],
            },
        ]
    }
    broken = {"views": [params["views"][0], {**params["views"][1], "sheet_id": str(uuid4())}]}
    with pytest.raises(MycadError):
        loaded.bus.execute("drawing.view.create", broken, "test")
    assert not services.kernel.drawing_state.views
    assert len(loaded.document.commands) == 2
    loaded.bus.execute("drawing.view.create", params, "test")
    assert len(services.kernel.drawing_state.views) == 2
    loaded.bus.undo()
    assert not services.kernel.drawing_state.views
    loaded.bus.redo()
    assert services.kernel.drawing_state.effective_anchor(child) == (0, -50)


def test_drawing2d_rejects_engineering_commands() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    with pytest.raises(MycadError):
        loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())}, "test")
    assert not loaded.document.commands


def test_unknown_properties_and_invalid_identity_rejected() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    for params in ({"sheet_id": "invalid"}, {"sheet_id": str(uuid4()), "unknown": True}):
        with pytest.raises(MycadError):
            loaded.bus.execute("drawing.sheet.create", params, "test")
    assert not loaded.document.commands


def test_drawing_cli_roundtrip() -> None:
    from mycad.commands.grammar import parse_line, to_cli

    services = build_app(discoverers=[])
    params = {"views": [{"view_id": str(uuid4()), "sheet_id": str(uuid4())}]}
    line = to_cli("drawing.view.create", params, services.registry)
    assert parse_line(line, services.registry) == ("drawing.view.create", params)


def test_confirmed_drawing_batch_rolls_back_missing_parent() -> None:
    from mycad.agent.plan_types import Plan
    from mycad.core.document import PlannedCommand

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    sheet = str(uuid4())
    plan = Plan(
        steps=[
            PlannedCommand(
                "drawing.sheet.create", 1, {"sheet_id": sheet}, "Create sheet", "drawing_sheet"
            ),
            PlannedCommand(
                "drawing.view.create",
                1,
                {"view_id": str(uuid4()), "sheet_id": sheet, "parent_id": str(uuid4())},
                "Create view",
                "drawing_view",
            ),
        ]
    )
    loaded.bus.confirm_plan(plan, "test", scope="cli")
    with pytest.raises(MycadError):
        loaded.bus.execute_batch(plan, scope="cli")
    assert not services.kernel.drawing_state.sheets
    assert len(loaded.document.commands) == 1
    assert loaded.document.archive_version == 1


def test_projected_orientation_follows_parent() -> None:
    from mycad.core.drawing_projection import ViewBasis, projected_basis

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    sheet, base, child = (str(uuid4()) for _ in range(3))
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": sheet})
    loaded.bus.execute(
        "drawing.view.create",
        {
            "views": [
                {"view_id": base, "sheet_id": sheet},
                {"view_id": child, "sheet_id": sheet, "parent_id": base, "direction": "top"},
            ]
        },
    )
    from uuid import UUID

    state = services.kernel.drawing_state
    assert state.effective_basis(UUID(child)) == projected_basis(ViewBasis(), "top")
    basis = ViewBasis.from_normal_up((1, 0, 0), (0, 0, 1))
    loaded.bus.execute(
        "drawing.view.update",
        {
            "view_id": base,
            "basis": {
                "right": list(basis.right),
                "up": list(basis.up),
                "normal": list(basis.normal),
            },
        },
    )
    assert services.kernel.drawing_state.effective_basis(UUID(child)) == projected_basis(
        basis, "top"
    )


def test_full_drawing_dto_can_be_committed_and_roundtripped_in_cli() -> None:
    from mycad.commands.grammar import parse_line, to_cli
    from mycad.core.drawing import DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    params = drawing_object_mapping(DrawingView(uuid4(), sheet))
    loaded.bus.execute("drawing.view.create", params)
    assert parse_line(
        to_cli("drawing.view.create", params, services.registry), services.registry
    ) == ("drawing.view.create", params)


def test_empty_model_cannot_create_view_or_change_history() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    sheet = str(uuid4())
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": sheet})
    before = tuple(loaded.document.commands)
    with pytest.raises(MycadError, match="实体|solid"):
        loaded.bus.execute("drawing.view.create", {"view_id": str(uuid4()), "sheet_id": sheet})
    assert tuple(loaded.document.commands) == before
    assert not services.kernel.drawing_state.views
