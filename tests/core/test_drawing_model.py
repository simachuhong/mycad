# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Engineering drawing state is independent, immutable and replayable."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad.core.drawing import (
    DrawingOperation,
    DrawingSheet,
    DrawingState,
    DrawingView,
    apply_drawing_operation,
    projected_offset,
)


@pytest.mark.parametrize(
    "angle,top,left", [("first", (0, -50), (50, 0)), ("third", (0, 50), (-50, 0))]
)
def test_first_and_third_angle_layout(
    angle: str, top: tuple[int, int], left: tuple[int, int]
) -> None:
    assert projected_offset(angle, "top", 50) == top
    assert projected_offset(angle, "left", 50) == left


def test_parent_cycles_and_cross_sheet_links_rejected() -> None:
    sheet = DrawingSheet(uuid4())
    other = DrawingSheet(uuid4())
    base = DrawingView(uuid4(), sheet.sheet_id)
    child = DrawingView(
        uuid4(), sheet.sheet_id, parent_id=base.view_id, direction="top", offset_mm=(0, -50)
    )
    state = DrawingState((sheet, other), (base, child))
    with pytest.raises(ValueError, match="cycle"):
        apply_drawing_operation(
            state,
            DrawingOperation(
                "update", "view", base.view_id, replace(base, parent_id=child.view_id)
            ),
        )
    with pytest.raises(ValueError, match="sheet"):
        apply_drawing_operation(
            state,
            DrawingOperation(
                "update", "view", child.view_id, replace(child, sheet_id=other.sheet_id)
            ),
        )
    assert state.views == (base, child)


def test_parent_move_scale_override_and_restore() -> None:
    sheet = DrawingSheet(uuid4())
    base = DrawingView(uuid4(), sheet.sheet_id, anchor_mm=(60, 100), scale=0.5)
    child = DrawingView(
        uuid4(), sheet.sheet_id, parent_id=base.view_id, direction="top", offset_mm=(0, -50)
    )
    state = DrawingState((sheet,), (base, child))
    assert state.effective_anchor(child.view_id) == (60, 50)
    assert state.effective_scale(child.view_id) == 0.5
    moved = apply_drawing_operation(
        state, DrawingOperation("update", "view", base.view_id, replace(base, anchor_mm=(80, 120)))
    )
    assert moved.effective_anchor(child.view_id) == (80, 70)
    overridden = apply_drawing_operation(
        moved,
        DrawingOperation(
            "update", "view", child.view_id, replace(child, inherit_scale=False, scale=2)
        ),
    )
    assert overridden.effective_scale(child.view_id) == 2
    restored = apply_drawing_operation(
        overridden, DrawingOperation("update", "view", child.view_id, child)
    )
    assert restored.effective_scale(child.view_id) == 0.5


def test_delete_parent_cascades_and_original_state_remains_intact() -> None:
    sheet = DrawingSheet(uuid4())
    base = DrawingView(uuid4(), sheet.sheet_id)
    child = DrawingView(
        uuid4(), sheet.sheet_id, parent_id=base.view_id, direction="left", offset_mm=(50, 0)
    )
    state = DrawingState((sheet,), (base, child))
    removed = apply_drawing_operation(state, DrawingOperation("delete", "view", base.view_id))
    assert not removed.views
    assert len(state.views) == 2


def test_changing_sheet_default_does_not_rearrange_existing_views() -> None:
    sheet = DrawingSheet(uuid4())
    base = DrawingView(uuid4(), sheet.sheet_id)
    child = DrawingView(
        uuid4(), sheet.sheet_id, parent_id=base.view_id, direction="top", offset_mm=(0, -50)
    )
    state = DrawingState((sheet,), (base, child))
    changed = apply_drawing_operation(
        state,
        DrawingOperation(
            "update", "sheet", sheet.sheet_id, replace(sheet, projection_angle="third")
        ),
    )
    assert changed.effective_anchor(child.view_id) == (0, -50)


@pytest.mark.parametrize("scale", [0, -1, float("nan"), float("inf"), True])
def test_invalid_scale_rejected(scale: float) -> None:
    with pytest.raises(ValueError, match="scale"):
        DrawingView(uuid4(), uuid4(), scale=scale)


def test_parent_delete_removes_annotations_atomically() -> None:
    from mycad.core.drawing import DrawingAnnotation
    from mycad.core.drawing_references import DrawingGeometryReference

    sheet = DrawingSheet(uuid4())
    view = DrawingView(uuid4(), sheet.sheet_id)
    dimension = DrawingAnnotation(
        uuid4(), view.view_id, "diameter", (DrawingGeometryReference("cylindrical_face"),), (10, 20)
    )
    state = DrawingState((sheet,), (view,), (dimension,))
    result = apply_drawing_operation(state, DrawingOperation("delete", "sheet", sheet.sheet_id))
    assert not result.sheets and not result.views and not result.annotations
    assert state.annotations == (dimension,)


def test_creation_is_unique_and_update_cannot_create_objects() -> None:
    sheet = DrawingSheet(uuid4())
    state = DrawingState((sheet,))
    with pytest.raises(ValueError, match="exists"):
        apply_drawing_operation(state, DrawingOperation("create", "sheet", sheet.sheet_id, sheet))
    new = DrawingSheet(uuid4())
    with pytest.raises(ValueError, match="does not exist"):
        apply_drawing_operation(state, DrawingOperation("update", "sheet", new.sheet_id, new))
