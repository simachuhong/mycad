# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Document-local design references, separate from runtime topology handles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from mycad.core.command_identity import require_instance_id
from mycad.core.exceptions import TopologyReferenceError, ValidationError

BOUND_FACE_ROLES = (
    "box.+X",
    "box.-X",
    "box.+Y",
    "box.-Y",
    "box.+Z",
    "box.-Z",
    "cylinder.top",
    "cylinder.bottom",
)


@dataclass(frozen=True, slots=True)
class BoundFaceRef:
    """A planar role born at a recorded command instance in this document."""

    source_instance_id: str
    role: str

    def __post_init__(self) -> None:
        require_instance_id(self.source_instance_id)
        if self.role not in BOUND_FACE_ROLES:
            raise ValidationError("unsupported bound face role")

    def to_mapping(self) -> dict[str, object]:
        return {
            "kind": "bound_face",
            "source_instance_id": self.source_instance_id,
            "role": self.role,
        }

    @classmethod
    def from_mapping(cls, value: object) -> BoundFaceRef:
        if not isinstance(value, Mapping):
            raise ValidationError("bound face must be an object")
        record = cast("Mapping[str, object]", value)
        if set(record) != {"kind", "source_instance_id", "role"} or record["kind"] != "bound_face":
            raise ValidationError("invalid bound face fields")
        role = record["role"]
        if not isinstance(role, str):
            raise ValidationError("bound face role must be a string")
        return cls(require_instance_id(record["source_instance_id"]), role)


def is_bound_hole(command_id: str, params: Mapping[str, object]) -> bool:
    """Recognize the released opt-in branch for conditional v5 preflight."""
    target = params.get("target_face")
    return (
        command_id == "feature.hole"
        and isinstance(target, Mapping)
        and cast("Mapping[str, object]", target).get("kind") == "bound_face"
    )


def validate_hole_binding(params: Mapping[str, object], *, ordinal: int | None = None) -> None:
    """Check the strict DTO before handlers or archive loading can touch geometry."""
    try:
        BoundFaceRef.from_mapping(params.get("target_face"))
    except ValidationError as exc:
        raise TopologyReferenceError(
            exc.message,
            command_id="feature.hole",
            ordinal=ordinal,
            reason="invalid-reference",
            parameter_path="target_face",
        ) from exc
