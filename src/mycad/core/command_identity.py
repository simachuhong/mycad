# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Persistent command identity, independent of runtime topology and CAD types."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from mycad.core.exceptions import ValidationError


def require_instance_id(value: object) -> str:
    """Require one canonical lowercase hex UUID on the v5 wire."""
    if not isinstance(value, str):
        raise ValidationError("instance_id must be a canonical hex UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValidationError("instance_id must be a canonical hex UUID") from exc
    if value != parsed.hex:
        raise ValidationError("instance_id must be a canonical hex UUID")
    return value


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """The recorded command identity/version supplied to a contextual kernel."""

    command_id: str
    command_version: int = 1
    instance_id: str | None = None

    def __post_init__(self) -> None:
        if self.instance_id is not None:
            require_instance_id(self.instance_id)


@dataclass(frozen=True, slots=True)
class IdentityUpgrade:
    """Bus-signed proposal; preparing it does not modify document or redo state."""

    document_id: str
    revision: int
    active_ids: tuple[str, ...]
    redo_ids: tuple[str, ...]
    signature: str
