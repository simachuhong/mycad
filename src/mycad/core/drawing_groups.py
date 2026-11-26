# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Stable references and selection semantics for independent drawing groups."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import cast
from uuid import UUID

_KINDS = frozenset(
    {
        "geometry",
        "text",
        "dimension",
        "reference_dimension",
        "tolerance",
        "datum",
        "raster",
        "block_instance",
    }
)


def _identity(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("object identity must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("object identity must be a canonical UUID") from exc
    if value not in (parsed.hex, str(parsed)):
        raise ValueError("object identity must be a canonical UUID")
    return value


@dataclass(frozen=True, slots=True)
class DrawingObjectRef:
    """An entire drawing object; geometry additionally identifies its sketch."""

    kind: str
    object_id: str
    sketch_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError("unsupported drawing object kind")
        _identity(self.object_id)
        if self.kind in ("geometry", "dimension"):
            _identity(self.sketch_id)
        elif self.sketch_id is not None:
            raise ValueError("sketch identity is only valid for sketch objects")

    def to_mapping(self) -> dict[str, object]:
        return {"kind": self.kind, "object_id": self.object_id, "sketch_id": self.sketch_id}

    @classmethod
    def from_mapping(cls, value: object) -> DrawingObjectRef:
        if not isinstance(value, Mapping):
            raise ValueError("invalid drawing object reference")
        data = cast("Mapping[str, object]", value)
        if set(data) != {"kind", "object_id", "sketch_id"}:
            raise ValueError("invalid drawing object reference fields")
        kind, object_id, sketch_id = data["kind"], data["object_id"], data["sketch_id"]
        if not isinstance(kind, str) or not isinstance(object_id, str):
            raise ValueError("invalid drawing object reference")
        if sketch_id is not None and not isinstance(sketch_id, str):
            raise ValueError("invalid sketch identity")
        return cls(kind, object_id, sketch_id)


@dataclass(frozen=True, slots=True)
class DrawingGroup:
    """Named or anonymous group of independent drawing objects."""

    group_id: str
    members: tuple[DrawingObjectRef, ...]
    name: str | None = None
    description: str = ""
    selectable: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "members", tuple(self.members))
        _identity(self.group_id)
        if not self.members or not all(
            isinstance(cast("object", item), DrawingObjectRef) for item in self.members
        ):
            raise ValueError("group requires drawing objects")
        if len(set(self.members)) != len(self.members):
            raise ValueError("group members must be unique")
        if self.name is not None and (
            not isinstance(cast("object", self.name), str) or not self.name.strip()
        ):
            raise ValueError("group name must be nonempty")
        if not isinstance(cast("object", self.description), str) or not isinstance(
            cast("object", self.selectable), bool
        ):
            raise ValueError("invalid group properties")

    def to_mapping(self) -> dict[str, object]:
        return {
            "group_id": self.group_id,
            "members": [item.to_mapping() for item in self.members],
            "name": self.name,
            "description": self.description,
            "selectable": self.selectable,
        }

    @classmethod
    def from_mapping(cls, value: object) -> DrawingGroup:
        if not isinstance(value, Mapping):
            raise ValueError("invalid drawing group")
        data = cast("Mapping[str, object]", value)
        if set(data) != {"group_id", "members", "name", "description", "selectable"}:
            raise ValueError("invalid drawing group fields")
        members = data["members"]
        if not isinstance(members, list):
            raise ValueError("group members must be a list")
        name, description, selectable = data["name"], data["description"], data["selectable"]
        if name is not None and not isinstance(name, str):
            raise ValueError("invalid group name")
        if not isinstance(description, str) or not isinstance(selectable, bool):
            raise ValueError("invalid group properties")
        return cls(
            _identity(data["group_id"]),
            tuple(DrawingObjectRef.from_mapping(item) for item in cast("list[object]", members)),
            name,
            description,
            selectable,
        )


@dataclass(frozen=True, slots=True)
class DrawingGroupTable:
    """Immutable group state suitable for candidates and operation history."""

    groups: tuple[DrawingGroup, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "groups", tuple(self.groups))
        ids = [UUID(group.group_id).hex for group in self.groups]
        names = [group.name.casefold() for group in self.groups if group.name is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("group identity already exists")
        if len(names) != len(set(names)):
            raise ValueError("group name already exists")

    def add(self, group: DrawingGroup) -> DrawingGroupTable:
        return DrawingGroupTable((*self.groups, group))

    def update(self, group: DrawingGroup) -> DrawingGroupTable:
        if all(item.group_id != group.group_id for item in self.groups):
            raise ValueError("group does not exist")
        return DrawingGroupTable(
            tuple(group if item.group_id == group.group_id else item for item in self.groups)
        )

    def remove(self, group_id: str) -> DrawingGroupTable:
        if all(item.group_id != group_id for item in self.groups):
            raise ValueError("group does not exist")
        return DrawingGroupTable(tuple(item for item in self.groups if item.group_id != group_id))

    def without_members(self, removed: Iterable[DrawingObjectRef]) -> DrawingGroupTable:
        removed_set = frozenset(removed)
        result: list[DrawingGroup] = []
        for group in self.groups:
            members = tuple(item for item in group.members if item not in removed_set)
            if members:
                result.append(replace(group, members=members))
        return DrawingGroupTable(tuple(result))


def expand_group_selection(
    selected: Iterable[DrawingObjectRef], groups: Iterable[DrawingGroup]
) -> frozenset[DrawingObjectRef]:
    """Expand only groups containing an originally selected object."""
    original = frozenset(selected)
    expanded = set(original)
    for group in groups:
        if group.selectable and not original.isdisjoint(group.members):
            expanded.update(group.members)
    return frozenset(expanded)
