# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Verify rigid dimension placement changes in replayed sketch revisions."""

from __future__ import annotations

import math
from dataclasses import fields, replace
from typing import cast

from mycad.core.sketch import Sketch
from mycad.core.sketch_constraints import DIMENSION_KINDS, SketchConstraint
from mycad.core.sketch_edit import move_entities


def _same_value(first: object, second: object) -> bool:
    if isinstance(first, float) and isinstance(second, float):
        return math.isclose(first, second, rel_tol=0.0, abs_tol=1e-10)
    if isinstance(first, tuple) and isinstance(second, tuple):
        first_items = cast("tuple[object, ...]", first)
        second_items = cast("tuple[object, ...]", second)
        return len(first_items) == len(second_items) and all(
            _same_value(left, right) for left, right in zip(first_items, second_items, strict=True)
        )
    return first == second


def is_rigid_dimension_translation(
    before: SketchConstraint, after: SketchConstraint, original: Sketch, revised: Sketch
) -> bool:
    """Accept only placement translated together with every referenced entity."""
    if (
        before.kind not in DIMENSION_KINDS
        or replace(after, position_mm=before.position_mm, text_position_mm=before.text_position_mm)
        != before
    ):
        return False
    pairs = (
        (before.position_mm, after.position_mm),
        (before.text_position_mm, after.text_position_mm),
    )
    if any((old is None) != (new is None) for old, new in pairs):
        return False
    changes = [(old, new) for old, new in pairs if old is not None and new is not None]
    if not changes:
        return False
    first, last = changes[0]
    delta = (last[0] - first[0], last[1] - first[1])
    if not all(
        math.isclose(new[index], old[index] + delta[index], rel_tol=0.0, abs_tol=1e-10)
        for old, new in changes
        for index in (0, 1)
    ):
        return False
    identities = tuple(dict.fromkeys(ref.entity_id for ref in before.references))
    try:
        expected = move_entities(
            original.entities, identities, delta, preserve_rectangle_order=True
        )
    except ValueError:
        return False
    expected_by_id = {entity.entity_id: entity for entity in expected}
    actual_by_id = {entity.entity_id: entity for entity in revised.entities}
    for identity in identities:
        expected_entity = expected_by_id.get(identity)
        actual_entity = actual_by_id.get(identity)
        if (
            expected_entity is None
            or actual_entity is None
            or type(expected_entity) is not type(actual_entity)
        ):
            return False
        if not all(
            _same_value(getattr(expected_entity, field.name), getattr(actual_entity, field.name))
            for field in fields(expected_entity)
        ):
            return False
    return True
