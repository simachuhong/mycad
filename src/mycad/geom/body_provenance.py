# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Track operation results with native shape identity, never approximate geometry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from build123d import Part, Solid

from mycad.core.selectors import BodySelector
from mycad.core.viewport_protocol import BodyInputRole, BodyOperationInput, BodyResultReference
from mycad.geom.selectors import resolve_body


class _ShapeIdentity(Protocol):
    """Narrow the upstream generic Shape method to the solids used here."""

    def is_same(self, other: Solid) -> bool: ...


@dataclass(frozen=True, slots=True)
class BodyOrigin:
    result: BodyResultReference
    inputs: tuple[BodyOperationInput, ...] = ()


def operation_origins(
    before: Part | None,
    after: Part | None,
    previous: tuple[BodyOrigin, ...],
    state_id: str,
    command_id: str,
    params: Mapping[str, object],
    *,
    rebuild: bool = False,
) -> tuple[BodyOrigin, ...]:
    """Retain unambiguously unchanged solids, record actual inputs for new results."""
    old = [] if before is None else list(before.solids())
    new = [] if after is None else list(after.solids())
    if len(old) != len(previous):
        raise ValueError("body provenance must align with the previous model")
    selected: list[tuple[BodyInputRole, int]] = []
    forced: set[int] = set()
    keys: tuple[tuple[BodyInputRole, str], ...] = ()
    if command_id == "modify.boolean_bodies":
        keys = (("target", "target_body"), ("tool", "tool_body"))
    elif command_id == "modify.body_transform":
        keys = (("source", "body"),)
    elif command_id == "modify.body_pattern":
        keys = (("seed", "seed_body"),)
    for role, key in keys:
        index, _solid = resolve_body(
            cast("BodySelector | Mapping[str, object]", params[key]), before, command_id
        )
        selected.append((role, index))
    if command_id == "modify.boolean_bodies":
        target, tool = (index for _role, index in selected)
        consumed = params.get("keep_tool", False) is False
        result_count = len(new) - len(old) + 1 + int(consumed)
        start = target - int(consumed and tool < target)
        forced.update(range(start, start + result_count))
    replacement = params.get("mode", "new") == "new" and command_id in (
        "feature.box",
        "feature.cylinder",
        "feature.extrude",
        "feature.revolve",
    )
    if replacement:
        inputs: tuple[BodyOperationInput, ...] = ()
        forced.update(range(len(new)))
    elif selected:
        inputs = tuple(BodyOperationInput(role, previous[index].result) for role, index in selected)
    else:
        inputs = tuple(BodyOperationInput("model", origin.result) for origin in previous)
    if rebuild:
        forced.update(range(len(new)))
    matches = [
        [index for index, prior in enumerate(old) if cast("_ShapeIdentity", solid).is_same(prior)]
        for solid in new
    ]
    result: list[BodyOrigin] = []
    for index, candidates in enumerate(matches):
        unique = len(candidates) == 1 and sum(candidates[0] in row for row in matches) == 1
        if index not in forced and unique:
            result.append(previous[candidates[0]])
        else:
            result.append(BodyOrigin(BodyResultReference(state_id, index), inputs))
    return tuple(result)
