# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Persistent references to document-local spatial design outputs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from mycad.core.command_identity import require_instance_id
from mycad.core.exceptions import ValidationError

SpatialKind = Literal["world", "coordinate_system", "datum_plane"]


@dataclass(frozen=True, slots=True)
class SpatialReference:
    """A world root or one typed, stable output of a recorded command."""

    kind: SpatialKind
    source_instance_id: str | None = None
    role: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "world":
            if self.source_instance_id is not None or self.role is not None:
                raise ValidationError("world reference cannot carry a source or role")
            return
        if self.kind not in ("coordinate_system", "datum_plane"):
            raise ValidationError("unknown spatial reference kind")
        require_instance_id(self.source_instance_id)
        expected = "coordinate_system" if self.kind == "coordinate_system" else "plane"
        if self.role != expected:
            raise ValidationError("invalid spatial output role")

    @classmethod
    def from_mapping(cls, value: object) -> SpatialReference:
        """Validate an exact tagged wire representation."""
        if not isinstance(value, Mapping):
            raise ValidationError("spatial reference must be an object")
        record = cast("Mapping[str, object]", value)
        if record.get("kind") == "world" and set(record) == {"kind"}:
            return cls("world")
        if set(record) != {"kind", "source_instance_id", "role"}:
            raise ValidationError("invalid spatial reference fields")
        kind = record["kind"]
        role = record["role"]
        if kind not in ("coordinate_system", "datum_plane") or not isinstance(role, str):
            raise ValidationError("invalid spatial reference type")
        return cls(
            cast("SpatialKind", kind), require_instance_id(record["source_instance_id"]), role
        )

    def to_mapping(self) -> dict[str, object]:
        """Serialize without runtime topology handles."""
        if self.kind == "world":
            return {"kind": "world"}
        return {"kind": self.kind, "source_instance_id": self.source_instance_id, "role": self.role}


def resolve_prior_output(
    reference: SpatialReference, outputs: Mapping[str, tuple[str, object]]
) -> object:
    """Resolve only already evaluated typed outputs; never guess a replacement."""
    if reference.kind == "world" or reference.source_instance_id is None:
        raise ValidationError("world is a root, not a recorded output")
    output = outputs.get(reference.source_instance_id)
    if output is None or output[0] != reference.kind:
        raise ValidationError("spatial reference does not name a prior output of the required kind")
    return output[1]
