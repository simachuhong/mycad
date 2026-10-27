# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Core document DTOs — the single definition site for the whole package.

Every other module must import ExecutedCommand / PlannedCommand /
AffectedObject / AFFECTED_OBJECTS from here; a second definition site
anywhere else is a layering violation. The Document aggregate itself lands
in T6b (see the placeholder at the end of this file).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, cast

from mycad.core.document_kinds import DRAWING2D_COMMAND_IDS, DocumentType
from mycad.core.exceptions import UnknownCommandError


@dataclass(frozen=True)
class CommandAmendment:
    """Audit-trail entry appended when a command's params are edited."""

    at: str
    actor: str
    from_params: dict[str, object]
    reason: str


@dataclass(frozen=True)
class ExecutedCommand:
    """One executed modeling command: six audit fields plus the revision trail.

    ``amendments`` is empty for newly executed commands and is excluded from
    the six-field audit count; archives omit the key while it is empty.
    """

    id: str
    version: int
    params: dict[str, object]
    ordinal: int
    timestamp_utc: str
    confirmed_by: str | None
    amendments: tuple[CommandAmendment, ...] = ()


AffectedObject = Literal[
    "box_body",
    "cylinder_body",
    "extruded_body",
    "revolved_body",
    "hole",
    "hole_pattern",
    "edge",
    "chamfer_edge",
    "tool_body",
    "intersection_tool_body",
    "body_pair",
    "body_transform",
    "body_pattern",
    "drawing_sheet",
    "drawing_view",
    "drawing_annotation",
]

# Appendix B.2 fixed mapping (command id -> affected_object), single source.
AFFECTED_OBJECTS: Mapping[str, str] = {
    "feature.box": "box_body",
    "feature.cylinder": "cylinder_body",
    "feature.extrude": "extruded_body",
    "feature.revolve": "revolved_body",
    "feature.hole": "hole",
    "feature.hole_pattern": "hole_pattern",
    "modify.fillet": "edge",
    "modify.chamfer": "chamfer_edge",
    "modify.boolean_cut": "tool_body",
    "modify.boolean_intersect": "intersection_tool_body",
    "modify.boolean_bodies": "body_pair",
    "modify.body_transform": "body_transform",
    "modify.body_pattern": "body_pattern",
    "drawing.sheet.create": "drawing_sheet",
    "drawing.sheet.update": "drawing_sheet",
    "drawing.sheet.delete": "drawing_sheet",
    "drawing.view.create": "drawing_view",
    "drawing.view.update": "drawing_view",
    "drawing.view.delete": "drawing_view",
    "drawing.annotation.create": "drawing_annotation",
    "drawing.annotation.update": "drawing_annotation",
    "drawing.annotation.delete": "drawing_annotation",
}


@dataclass(frozen=True)
class PlannedCommand:
    """One planned step; ``summary_en`` is copied from the registry spec.

    Dual gate: the ``AffectedObject`` Literal locks the released values
    statically (basedpyright), while ``__post_init__`` locks the command id
    at runtime via the AFFECTED_OBJECTS table.
    """

    id: str
    version: int
    params: dict[str, object]
    summary_en: str
    affected_object: AffectedObject

    def __post_init__(self) -> None:
        if self.id not in AFFECTED_OBJECTS:
            raise UnknownCommandError(f"unknown command id {self.id!r}", identifier=self.id)


# T6b: Document 类在此追加

from typing import TYPE_CHECKING  # noqa: E402 — the DTO header above is frozen (a2 slice)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mycad.commands.registry import CommandRegistry
    from mycad.core.groups import NamedGroup

#: v1 metadata cap: exactly these six keys; anything else is a ValidationError.
METADATA_KEYS = ("part_no", "revision", "material", "source", "part_name", "notes")

#: A ``new`` document starts with exactly these four keys (no part_name/notes).
DEFAULT_METADATA: dict[str, str] = {
    "part_no": "",
    "revision": "",
    "material": "",
    "source": "local",
}


class Document:
    """Single-threaded document model (no write lock — phase 0 "Must NOT do").

    Metadata and named groups are document annotations: they never enter the
    geometry replay sequence and never trigger a rebuild. Geometry replay is
    Bus-side (T6c), not here.
    """

    def __init__(
        self,
        registry: CommandRegistry,
        *,
        metadata: Mapping[str, str] | None = None,
        commands: Iterable[ExecutedCommand] | None = None,
        named_groups: Mapping[str, NamedGroup] | None = None,
        archive_version: int = 1,
        document_type: DocumentType = "part",
    ) -> None:
        from mycad.core.exceptions import ValidationError
        from mycad.core.signals import SignalBus

        self._registry = registry
        self._document_id = uuid.uuid4().hex
        self._revision = 0
        version_value = cast("object", archive_version)
        if (
            isinstance(version_value, bool)
            or not isinstance(version_value, int)
            or version_value < 1
        ):
            raise ValidationError("archive_version must be an integer >= 1")
        self._archive_version = version_value
        document_type_value = cast("object", document_type)
        if document_type_value not in ("part", "drawing2d"):
            raise ValidationError("document_type must be 'part' or 'drawing2d'")
        if document_type_value == "drawing2d" and version_value < 3:
            raise ValidationError("drawing2d documents require archive_version 3 or later")
        self._document_type: DocumentType = document_type
        if metadata is None:
            self._metadata: dict[str, str] = dict(DEFAULT_METADATA)
        else:
            for key in metadata:
                if key not in METADATA_KEYS:
                    raise ValidationError(f"unknown metadata key {key!r}")
            self._metadata = dict(metadata)
        self._commands: list[ExecutedCommand] = (
            deepcopy(list(commands)) if commands is not None else []
        )
        if self._document_type == "drawing2d":
            for command in self._commands:
                if command.id not in DRAWING2D_COMMAND_IDS:
                    raise ValidationError(
                        f"drawing2d document cannot contain command {command.id!r}"
                    )
        self._named_groups: dict[str, NamedGroup] = (
            dict(named_groups) if named_groups is not None else {}
        )
        if self._document_type == "drawing2d" and self._named_groups:
            raise ValidationError("drawing2d documents cannot contain 3D named groups")
        self._dirty = False
        self.events = SignalBus()

    @property
    def document_id(self) -> str:
        """Runtime identity for this in-memory document instance."""
        return self._document_id

    @property
    def revision(self) -> int:
        """Monotonic revision of committed document content changes."""
        return self._revision

    @property
    def archive_version(self) -> int:
        """Minimum archive schema required by this document's command history."""
        return self._archive_version

    @property
    def document_type(self) -> DocumentType:
        """Persisted semantic kind; only archive migrations may establish it."""
        return self._document_type

    def _advance_revision(self) -> None:
        """Record one committed content change; Bus owns command-history calls."""
        self._revision += 1

    @property
    def metadata(self) -> dict[str, str]:
        """Copy of the six-key v1 metadata mapping."""
        return dict(self._metadata)

    def set_metadata(self, key: str, value: str) -> None:
        """Set one whitelisted metadata key — document annotation, no history."""
        from typing import cast

        from mycad.core.exceptions import ValidationError

        if key not in METADATA_KEYS:
            raise ValidationError(f"unknown metadata key {key!r}")
        # Runtime check of untrusted input; cast keeps it non-redundant for pyright.
        if not isinstance(cast("object", value), str):
            raise ValidationError(f"metadata value for {key!r} must be a string")
        self._metadata[key] = value
        self._dirty = True
        self._advance_revision()
        self.events.emit("metadata_changed", {"key": key, "value": value})

    @property
    def is_dirty(self) -> bool:
        """True when unsaved changes exist."""
        return self._dirty

    def mark_clean(self) -> None:
        """Clear the dirty flag (save path calls this after persistence)."""
        self._dirty = False

    @property
    def named_groups(self) -> dict[str, NamedGroup]:
        """Copy of the named groups mapping (CAE seam; document annotation)."""
        return dict(self._named_groups)

    def add_named_group(self, group: NamedGroup) -> None:
        """Store a group; its name must be a non-empty, not-yet-taken string."""
        from typing import cast

        from mycad.core.exceptions import ValidationError

        if self._document_type == "drawing2d":
            raise ValidationError("drawing2d documents cannot contain 3D named groups")
        name = group.name
        if not isinstance(cast("object", name), str) or not name:
            raise ValidationError(f"named group name must be a non-empty string, got {name!r}")
        if name in self._named_groups:
            raise ValidationError(f"named group {name!r} already exists")
        self._named_groups[name] = group
        self._dirty = True
        self._advance_revision()
        self.events.emit("named_group_added", {"name": name})

    def remove_named_group(self, name: str) -> None:
        """Drop a group by name; a missing name raises KeyError (T10 runtime error 1)."""
        if name not in self._named_groups:
            raise KeyError(name)
        del self._named_groups[name]
        self._dirty = True
        self._advance_revision()
        self.events.emit("named_group_removed", {"name": name})

    def metadata_snapshot(self) -> dict[str, str]:
        """Snapshot of metadata for Bus-side batch rollback (T6c)."""
        return dict(self._metadata)

    def _restore_metadata(self, snapshot: Mapping[str, str]) -> None:
        """Replace metadata wholesale from a snapshot (marks the document dirty)."""
        self._metadata = dict(snapshot)
        self._dirty = True

    @property
    def commands(self) -> tuple[ExecutedCommand, ...]:
        """Detached history snapshot, including nested params and audit data.

        Frozen command DTOs still contain mutable JSON dictionaries/lists.
        Callers may inspect or edit their copy, but only Bus-side operations
        can change the stored history and trigger geometry/dirty updates.
        """
        return deepcopy(tuple(self._commands))

    def replace_command_params(
        self,
        ordinal: int,
        params: Mapping[str, object],
        actor: str,
        reason: str,
    ) -> ExecutedCommand:
        """Edit one history entry's params (#10 sole entry point; no geometry here).

        Re-validates against the registry spec (failure leaves the document
        untouched), swaps the slot in via a defensive deep copy, appends a
        CommandAmendment preserving the original audit fields, advances the
        document revision, emits ``command_amended`` and returns the revised
        command. Bus-side replay uses the private deferred helper so a failed
        transaction can restore its snapshot without committing a revision.
        """
        return self._replace_command_params(
            ordinal, params, actor, reason, notify=True, advance_revision=True
        )

    def _replace_command_params(
        self,
        ordinal: int,
        params: Mapping[str, object],
        actor: str,
        reason: str,
        *,
        notify: bool,
        advance_revision: bool,
    ) -> ExecutedCommand:
        """Replace history inside an optional Bus transaction boundary."""
        from dataclasses import replace
        from datetime import UTC, datetime

        from mycad.commands.validation import validate_params
        from mycad.core.exceptions import InvalidHistoryError

        if not 0 <= ordinal < len(self._commands):
            raise InvalidHistoryError(f"ordinal {ordinal} not in history")
        cmd = self._commands[ordinal]
        spec = self._registry.get(cmd.id, cmd.version)
        validate_params(spec, params, defs=self._registry.schema_defs)
        snapshot = list(self._commands)
        new_cmd = replace(
            cmd,
            params=deepcopy(dict(params)),
            amendments=cmd.amendments
            + (
                CommandAmendment(
                    at=datetime.now(UTC).isoformat(),
                    actor=actor,
                    from_params=deepcopy(cmd.params),
                    reason=reason,
                ),
            ),
        )
        snapshot[ordinal] = new_cmd
        self._commands = snapshot
        self._dirty = True
        if advance_revision:
            self._advance_revision()
        if notify:
            self.events.emit(
                "command_amended",
                {"ordinal": ordinal, "command_id": cmd.id, "command_version": cmd.version},
            )
        return deepcopy(new_cmd)

    def _snapshot_state(
        self,
    ) -> tuple[list[ExecutedCommand], dict[str, str], dict[str, NamedGroup], bool, int]:
        """Capture all mutable document state for a Bus transaction."""
        return (
            deepcopy(self._commands),
            dict(self._metadata),
            deepcopy(self._named_groups),
            self._dirty,
            self._archive_version,
        )

    def _restore_state(
        self,
        snapshot: tuple[list[ExecutedCommand], dict[str, str], dict[str, NamedGroup], bool, int],
    ) -> None:
        """Restore a complete Bus transaction snapshot without emitting events."""
        commands, metadata, named_groups, dirty, archive_version = snapshot
        self._commands = deepcopy(commands)
        self._metadata = dict(metadata)
        self._named_groups = deepcopy(named_groups)
        self._dirty = dirty
        self._archive_version = archive_version

    def _append_command(self, command: ExecutedCommand) -> None:
        """Bus-side append (T6c): the single write path into the history list."""
        spec = self._registry.get(command.id, command.version)
        self._commands.append(deepcopy(command))
        self._archive_version = max(self._archive_version, spec.min_archive_version)
        self._dirty = True

    def _pop_commands(self, n: int) -> list[ExecutedCommand]:
        """Bus-side rollback primitive: pop the trailing ``n`` commands."""
        if n <= 0:
            return []
        popped = self._commands[-n:]
        del self._commands[-n:]
        self._dirty = True
        return popped

    def _restore_commands(self, snapshot: list[ExecutedCommand]) -> None:
        """Bus-side restore: replace the whole history (T6c batch rollback)."""
        self._commands = deepcopy(snapshot)
        self._dirty = True
