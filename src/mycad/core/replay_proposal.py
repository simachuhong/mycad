# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Backend-neutral values used to stage and authorize a replay candidate."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, cast

from mycad.core.command_identity import IdentityUpgrade
from mycad.core.document import ExecutedCommand
from mycad.core.exceptions import ValidationError

ReplayCandidateState = Literal[
    "ready", "previewing", "succeeded", "failed", "stale", "committed", "cancelled"
]


def _nonnegative_integer(name: str, value: object) -> None:
    if type(value) is not int or value < 0:
        raise ValidationError(f"{name} must be a non-negative integer")


def _json_copy(value: object, *, path: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError(f"{path} must contain finite JSON numbers")
        return value
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        if any(not isinstance(key, str) for key in mapping):
            raise ValidationError(f"{path} mapping keys must be strings")
        return {
            key: _json_copy(item, path=f"{path}.{key}")
            for key, item in mapping.items()
            if isinstance(key, str)
        }
    if isinstance(value, (list, tuple)):
        sequence = cast("Sequence[object]", value)
        return [_json_copy(item, path=f"{path}[{index}]") for index, item in enumerate(sequence)]
    raise ValidationError(f"{path} contains a value that is not JSON-compatible")


def _require_text(name: str, value: object, *, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValidationError(f"{name} must be a non-empty string")


def _json_mapping_copy(name: str, value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{name} must be a mapping")
    mapping = cast("Mapping[object, object]", value)
    copied = _json_copy(mapping, path=name)
    if not isinstance(copied, dict):
        raise ValidationError(f"{name} must be a mapping")
    return cast("dict[str, object]", copied)


@dataclass(frozen=True, slots=True)
class ReplayEdit:
    """One requested replacement of an existing command's normalized params."""

    ordinal: int
    params: Mapping[str, object]
    actor: str
    reason: str

    def __post_init__(self) -> None:
        _nonnegative_integer("ordinal", self.ordinal)
        _require_text("actor", self.actor)
        _require_text("reason", self.reason)
        object.__setattr__(self, "params", _json_mapping_copy("params", self.params))


@dataclass(frozen=True, slots=True)
class ReplayAppend:
    """One command to append to a candidate replay."""

    command_id: str
    version: int
    params: Mapping[str, object]
    confirmed_by: str | None

    def __post_init__(self) -> None:
        _require_text("command_id", self.command_id)
        if type(self.version) is not int or self.version < 1:
            raise ValidationError("version must be an integer >= 1")
        if self.confirmed_by is not None:
            _require_text("confirmed_by", self.confirmed_by)
        object.__setattr__(self, "params", _json_mapping_copy("params", self.params))


@dataclass(frozen=True, slots=True)
class ReplayChangeSet:
    """Complete set of edits, appends, and optional first-time v5 upgrade."""

    replacements: tuple[ReplayEdit, ...]
    appends: tuple[ReplayAppend, ...]
    upgrade_to_v5: bool
    target_archive_version: int | None = None
    undo_appends_separately: bool = False

    def __post_init__(self) -> None:
        raw_replacements = cast("tuple[object, ...]", tuple(deepcopy(self.replacements)))
        raw_appends = cast("tuple[object, ...]", tuple(deepcopy(self.appends)))
        if any(not isinstance(item, ReplayEdit) for item in raw_replacements):
            raise ValidationError("replacements must contain ReplayEdit values")
        if any(not isinstance(item, ReplayAppend) for item in raw_appends):
            raise ValidationError("appends must contain ReplayAppend values")
        if type(self.upgrade_to_v5) is not bool:
            raise ValidationError("upgrade_to_v5 must be a boolean")
        if type(self.undo_appends_separately) is not bool:
            raise ValidationError("undo_appends_separately must be a boolean")
        if self.undo_appends_separately and (raw_replacements or not raw_appends):
            raise ValidationError("separate append undo requires an append-only change set")
        if self.target_archive_version is not None and (
            type(self.target_archive_version) is not int or self.target_archive_version != 6
        ):
            raise ValidationError("target_archive_version must be 6 or None")
        replacements = cast("tuple[ReplayEdit, ...]", raw_replacements)
        appends = cast("tuple[ReplayAppend, ...]", raw_appends)
        object.__setattr__(self, "replacements", replacements)
        object.__setattr__(self, "appends", appends)


@dataclass(frozen=True, slots=True)
class ReplayCandidateProposal:
    """Frozen source binding and normalized complete command history."""

    document_id: str
    file_id: str
    revision: int
    session_identity: int
    candidate_id: str
    generation: int
    archive_version: int
    commands: tuple[ExecutedCommand, ...]
    identity_upgrade: IdentityUpgrade | None
    digest: str
    undo_appends_separately: bool = False

    def __post_init__(self) -> None:
        _require_text("document_id", self.document_id)
        _require_text("file_id", self.file_id)
        _require_text("candidate_id", self.candidate_id)
        _nonnegative_integer("revision", self.revision)
        _nonnegative_integer("session_identity", self.session_identity)
        _nonnegative_integer("generation", self.generation)
        if type(self.archive_version) is not int or not 1 <= self.archive_version <= 6:
            raise ValidationError("archive_version must be an integer from 1 to 6")
        _require_text("digest", self.digest)
        if type(self.undo_appends_separately) is not bool:
            raise ValidationError("undo_appends_separately must be a boolean")
        if len(self.digest) != 64:
            raise ValidationError("digest must be a SHA-256 hex digest")
        try:
            bytes.fromhex(self.digest)
        except ValueError as exc:
            raise ValidationError("digest must be a SHA-256 hex digest") from exc
        raw_commands = cast("tuple[object, ...]", tuple(deepcopy(self.commands)))
        if any(not isinstance(command, ExecutedCommand) for command in raw_commands):
            raise ValidationError("commands must contain ExecutedCommand values")
        identity_upgrade = cast("object", self.identity_upgrade)
        if identity_upgrade is not None and not isinstance(identity_upgrade, IdentityUpgrade):
            raise ValidationError("identity_upgrade must be an IdentityUpgrade or None")
        commands = cast("tuple[ExecutedCommand, ...]", raw_commands)
        object.__setattr__(self, "commands", commands)


@dataclass(frozen=True, slots=True)
class ReplayFailure:
    """Neutral location and reason for the first failed candidate command."""

    command_id: str
    command_version: int
    instance_id: str | None
    ordinal: int
    parameter_path: str | None
    reason: str
    last_successful_ordinal: int | None

    def __post_init__(self) -> None:
        _require_text("command_id", self.command_id)
        if type(self.command_version) is not int or self.command_version < 1:
            raise ValidationError("command_version must be an integer >= 1")
        _nonnegative_integer("ordinal", self.ordinal)
        if self.last_successful_ordinal is not None:
            _nonnegative_integer("last_successful_ordinal", self.last_successful_ordinal)
            if self.last_successful_ordinal >= self.ordinal:
                raise ValidationError("last_successful_ordinal must precede ordinal")
        if self.instance_id is not None:
            _require_text("instance_id", self.instance_id)
        if self.parameter_path is not None:
            _require_text("parameter_path", self.parameter_path)
        _require_text("reason", self.reason)


@dataclass(frozen=True, slots=True)
class ReplayCommitGrant:
    """Source-Bus-signed, one-time permission to commit one candidate result."""

    document_id: str
    file_id: str
    revision: int
    session_identity: int
    candidate_id: str
    generation: int
    digest: str
    nonce: str
    signature: str

    def __post_init__(self) -> None:
        _require_text("document_id", self.document_id)
        _require_text("file_id", self.file_id)
        _require_text("candidate_id", self.candidate_id)
        _nonnegative_integer("revision", self.revision)
        _nonnegative_integer("session_identity", self.session_identity)
        _nonnegative_integer("generation", self.generation)
        _require_text("digest", self.digest)
        _require_text("signature", self.signature)
        _require_text("nonce", self.nonce)


def _command_payload(command: ExecutedCommand, index: int) -> dict[str, object]:
    return {
        "id": command.id,
        "version": command.version,
        "params": _json_copy(command.params, path=f"commands[{index}].params"),
        "ordinal": command.ordinal,
        "timestamp_utc": command.timestamp_utc,
        "confirmed_by": command.confirmed_by,
        "amendments": [
            {
                "at": amendment.at,
                "actor": amendment.actor,
                "from_params": _json_copy(
                    amendment.from_params,
                    path=f"commands[{index}].amendments[{amendment_index}].from_params",
                ),
                "reason": amendment.reason,
            }
            for amendment_index, amendment in enumerate(command.amendments)
        ],
        "instance_id": command.instance_id,
    }


def replay_digest(archive_version: int, commands: Sequence[ExecutedCommand]) -> str:
    """Hash canonical JSON for the complete archive version and command history."""
    if type(archive_version) is not int or not 1 <= archive_version <= 6:
        raise ValidationError("archive_version must be an integer from 1 to 6")
    commands_value = cast("object", commands)
    if isinstance(commands_value, (str, bytes)) or not isinstance(commands_value, Sequence):
        raise ValidationError("commands must be a sequence of ExecutedCommand values")
    command_values = cast("Sequence[object]", commands_value)
    if any(not isinstance(command, ExecutedCommand) for command in command_values):
        raise ValidationError("commands must contain ExecutedCommand values")
    typed_commands = cast("Sequence[ExecutedCommand]", command_values)
    payload = {
        "archive_version": archive_version,
        "commands": [
            _command_payload(command, index) for index, command in enumerate(typed_commands)
        ],
    }
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValidationError("candidate history must contain finite JSON-compatible data") from exc
    return hashlib.sha256(encoded).hexdigest()
