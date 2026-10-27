# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Document persistence: atomic v1 JSON archive save/open (T6d).

Single-threaded document model (no write lock — phase 0 "Must NOT do").
Only core-side types and Protocols live here: registry, handlers and kernel
arrive as instances; ``CommandRegistry`` appears solely as a TYPE_CHECKING
annotation, so there is zero runtime import of ``mycad.commands``.
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mycad.core.bus import CommandBus
from mycad.core.document import CommandAmendment, Document, ExecutedCommand
from mycad.core.document_kinds import DocumentType
from mycad.core.exceptions import ArchiveVersionError, UnknownCommandError, ValidationError
from mycad.core.groups import NamedGroup
from mycad.core.handlers import CommandHandler, resolve_handler
from mycad.core.kernel_protocol import Kernel
from mycad.core.schema_v1 import (
    ARCHIVE_FORMAT,
    ARCHIVE_VERSION,
    selector_from_json,
    validate_archive,
)
from mycad.core.schema_v2 import ARCHIVE_VERSION_V2, validate_archive_v2
from mycad.core.schema_v3 import ARCHIVE_VERSION_V3, validate_archive_v3
from mycad.core.selectors import EdgeSelector, FaceSelector

if TYPE_CHECKING:
    from mycad.commands.registry import CommandRegistry

__all__ = ["LoadedDocument", "open_document", "save_document"]


@dataclass(frozen=True)
class LoadedDocument:
    """Result of ``open_document``: restored document plus assembled bus."""

    document: Document
    bus: CommandBus


def _face_to_json(selector: FaceSelector) -> dict[str, object]:
    """Wire form: None-valued axis/rank keys are omitted, never null."""
    data: dict[str, object] = {"surface": selector.surface}
    if selector.axis is not None:
        data["axis"] = selector.axis
    if selector.rank is not None:
        data["rank"] = selector.rank
    return data


def _edge_to_json(selector: EdgeSelector) -> dict[str, object]:
    """Wire form: the curve key is omitted when None; parent_faces always present."""
    data: dict[str, object] = {
        "parent_faces": [_face_to_json(face) for face in selector.parent_faces]
    }
    if selector.curve is not None:
        data["curve"] = selector.curve
    return data


def _archive_payload_v1(document: Document) -> dict[str, object]:
    """Assemble the v1 archive dict (stable key order; empty lists explicit)."""
    commands: list[dict[str, object]] = []
    for cmd in document.commands:
        entry: dict[str, object] = {
            "id": cmd.id,
            "version": cmd.version,
            "params": cmd.params,
            "ordinal": cmd.ordinal,
            "timestamp_utc": cmd.timestamp_utc,
            "confirmed_by": cmd.confirmed_by,
        }
        if cmd.amendments:
            entry["amendments"] = [
                {
                    "at": amendment.at,
                    "actor": amendment.actor,
                    "from_params": amendment.from_params,
                    "reason": amendment.reason,
                }
                for amendment in cmd.amendments
            ]
        commands.append(entry)
    named_groups = [
        {
            "name": group.name,
            "faces": [_face_to_json(sel) for sel in group.faces],
            "edges": [_edge_to_json(sel) for sel in group.edges],
        }
        for group in document.named_groups.values()
    ]
    return {
        "format": ARCHIVE_FORMAT,
        "version": ARCHIVE_VERSION,
        "metadata": document.metadata_snapshot(),
        "commands": commands,
        "named_groups": named_groups,
    }


def _distribution_version(name: str) -> str:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return "unavailable"


def _capture_provenance(
    plugin_identities: Mapping[tuple[str, int], Mapping[str, str]],
    commands: list[dict[str, object]],
) -> dict[str, object]:
    """Capture runtime facts without importing the CAD backend into core."""
    plugin_records: list[dict[str, object]] = []
    for command in commands:
        command_id = cast("str", command["id"])
        command_version = cast("int", command["version"])
        identity = plugin_identities.get((command_id, command_version))
        if identity is None:
            continue
        plugin_records.append(
            {
                "command_id": command_id,
                "command_version": command_version,
                "distribution": identity.get("distribution", "unavailable"),
                "plugin_id": identity.get("plugin_id", "unavailable"),
                "plugin_version": identity.get("plugin_version", "unavailable"),
                "api_version": identity.get("api_version", "unavailable"),
            }
        )
    plugin_records.sort(
        key=lambda item: (cast("str", item["command_id"]), cast("int", item["command_version"]))
    )
    source_revision = os.environ.get("MYCAD_SOURCE_REVISION", "unavailable") or "unavailable"
    return {
        "mycad": {
            "version": _distribution_version("mycad"),
            "source_revision": source_revision,
        },
        "python": {
            "implementation": platform.python_implementation() or "unavailable",
            "version": sys.version.split()[0] or "unavailable",
        },
        "dependencies": {
            "build123d": _distribution_version("build123d"),
            "ocp": _distribution_version("cadquery-ocp-novtk"),
            "occt": "unavailable",
            "planegcs": _distribution_version("planegcs"),
        },
        "units": {"length": "mm", "angle": "deg"},
        "geometry_policy_version": "1",
        "plugins": plugin_records,
    }


def _migrate_v1_to_v2(
    payload: dict[str, object], provenance: dict[str, object]
) -> dict[str, object]:
    """Pure v1→v2 data migration; validation brackets this single version hop."""
    validate_archive(payload)
    migrated = {**payload, "version": ARCHIVE_VERSION_V2, "provenance": provenance}
    validate_archive_v2(migrated)
    return migrated


def _migrate_v2_to_v3(payload: dict[str, object], document_type: DocumentType) -> dict[str, object]:
    """Pure v2→v3 migration that records the explicit document kind."""
    validate_archive_v2(payload)
    migrated = {
        **payload,
        "version": ARCHIVE_VERSION_V3,
        "document_type": document_type,
    }
    validate_archive_v3(migrated)
    return migrated


def save_document(
    document: Document,
    path: Path,
    *,
    plugin_identities: Mapping[tuple[str, int], Mapping[str, str]] | None = None,
) -> None:
    """Atomically write the document using its current archive schema version.

    Emits ``document_saving`` before and ``document_saved`` after the write.
    Atomicity is a same-directory temp file plus ``os.replace``; a missing
    parent directory propagates as ``OSError`` (never auto-created).
    """
    payload = _archive_payload_v1(document)
    if document.archive_version == ARCHIVE_VERSION:
        validate_archive(payload)
    elif document.archive_version == ARCHIVE_VERSION_V2:
        provenance = _capture_provenance(
            plugin_identities or {}, cast("list[dict[str, object]]", payload["commands"])
        )
        payload = _migrate_v1_to_v2(payload, provenance)
    elif document.archive_version == ARCHIVE_VERSION_V3:
        provenance = _capture_provenance(
            plugin_identities or {}, cast("list[dict[str, object]]", payload["commands"])
        )
        payload = _migrate_v2_to_v3(_migrate_v1_to_v2(payload, provenance), document.document_type)
    else:
        raise ArchiveVersionError(
            f"document archive version {document.archive_version} is not supported",
            found=str(document.archive_version),
            supported=ARCHIVE_VERSION_V3,
        )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    document.events.emit("document_saving", {"path": str(path)})
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".tmp", delete=False, dir=path.parent, encoding="utf-8"
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path is not None and tmp_path.exists():
            # A failed cleanup must not mask the error being re-raised.
            with contextlib.suppress(OSError):
                tmp_path.unlink()
        raise
    document.events.emit("document_saved", {"path": str(path)})


def _require_command(
    entry: Mapping[str, object],
    registry: CommandRegistry,
    handlers: Mapping[str, CommandHandler] | Mapping[tuple[str, int], CommandHandler],
) -> None:
    """Pre-flight one archive command against the registry and handlers."""
    command_id = entry["id"]
    version = entry["version"]
    ordinal = entry["ordinal"]
    try:
        registry.get(cast("str", command_id), cast("int", version))
    except UnknownCommandError:
        raise UnknownCommandError(
            f"archive command at ordinal {ordinal} has unknown id {command_id!r} "
            f"(version {version})",
            identifier=cast("str", command_id),
        ) from None
    if (
        resolve_handler(
            handlers,
            cast("str", command_id),
            cast("int", version),
            registry.versions(cast("str", command_id)),
        )
        is None
    ):
        raise UnknownCommandError(
            f"archive command at ordinal {ordinal} ({command_id!r} version {version}) has no handler",
            identifier=cast("str", command_id),
        )


def _command_from_json(entry: Mapping[str, object]) -> ExecutedCommand:
    """Rebuild one ExecutedCommand verbatim (no audit field is rewritten)."""
    amendments: list[CommandAmendment] = []
    for item in cast("list[object]", entry.get("amendments", [])):
        record = cast("dict[str, object]", item)
        amendments.append(
            CommandAmendment(
                at=cast("str", record["at"]),
                actor=cast("str", record["actor"]),
                from_params=dict(cast("Mapping[str, object]", record["from_params"])),
                reason=cast("str", record["reason"]),
            )
        )
    return ExecutedCommand(
        id=cast("str", entry["id"]),
        version=cast("int", entry["version"]),
        params=dict(cast("Mapping[str, object]", entry["params"])),
        ordinal=cast("int", entry["ordinal"]),
        timestamp_utc=cast("str", entry["timestamp_utc"]),
        confirmed_by=cast("str | None", entry["confirmed_by"]),
        amendments=tuple(amendments),
    )


def _build_document(
    data: dict[str, object],
    registry: CommandRegistry,
    *,
    archive_version: int,
    document_type: DocumentType = "part",
) -> Document:
    """Construct the Document aggregate from a validated archive dict."""
    commands = [
        _command_from_json(cast("Mapping[str, object]", entry))
        for entry in cast("list[object]", data["commands"])
    ]
    groups: dict[str, NamedGroup] = {}
    for index, raw_group in enumerate(cast("list[object]", data["named_groups"])):
        entry = cast("dict[str, object]", raw_group)
        name = cast("str", entry["name"])
        faces = tuple(
            cast("FaceSelector", selector_from_json(sel, f"named_groups/{index}/faces/{j}"))
            for j, sel in enumerate(cast("list[object]", entry["faces"]))
        )
        edges = tuple(
            cast("EdgeSelector", selector_from_json(sel, f"named_groups/{index}/edges/{j}"))
            for j, sel in enumerate(cast("list[object]", entry["edges"]))
        )
        groups[name] = NamedGroup(name=name, faces=faces, edges=edges)
    return Document(
        registry,
        metadata=cast("Mapping[str, str]", data["metadata"]),
        commands=commands,
        named_groups=groups,
        archive_version=archive_version,
        document_type=document_type,
    )


def open_document(
    path: Path,
    *,
    registry: CommandRegistry,
    kernel: Kernel,
    handlers: Mapping[str, CommandHandler] | Mapping[tuple[str, int], CommandHandler],
) -> LoadedDocument:
    """Read, validate, rebuild and assemble a document from ``path``.

    Pipeline (fixed order): read text -> parse JSON -> format check ->
    explicit version check -> version-specific structural validation ->
    per-command registry/handler pre-flight -> Document construction ->
    CommandBus assembly -> ONE full ``_rebuild()``. Replay never rewrites
    timestamps/ordinals/confirmed_by/amendments; a failing rebuild leaves
    no partially-constructed LoadedDocument behind.
    """
    raw = path.read_text(encoding="utf-8")  # OSError propagates (CLI's concern)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"archive: malformed JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise ValidationError("archive: top level must be a JSON object")
    root = cast("dict[str, object]", data)
    fmt = root.get("format")
    if fmt != ARCHIVE_FORMAT:
        found = fmt if isinstance(fmt, str) else "missing"
        raise ArchiveVersionError(
            f"archive format {found!r} is not supported (expected {ARCHIVE_FORMAT!r})",
            found=found,
            supported=ARCHIVE_FORMAT,
        )
    version = root.get("version")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version
        not in (
            ARCHIVE_VERSION,
            ARCHIVE_VERSION_V2,
            ARCHIVE_VERSION_V3,
        )
    ):
        raise ArchiveVersionError(
            f"archive version {version!r} is not supported (supported: 1, 2, {ARCHIVE_VERSION_V3})",
            found=str(version),
            supported=ARCHIVE_VERSION_V3,
        )
    archive_version = cast("int", version)
    document_type: DocumentType = "part"
    if archive_version == ARCHIVE_VERSION:
        validate_archive(root)
        replay_data = root
    elif archive_version == ARCHIVE_VERSION_V2:
        validate_archive_v2(root)
        replay_data = {key: value for key, value in root.items() if key != "provenance"}
        replay_data["version"] = ARCHIVE_VERSION
    else:
        validate_archive_v3(root)
        document_type = cast("DocumentType", root["document_type"])
        replay_data = {
            key: value for key, value in root.items() if key not in ("provenance", "document_type")
        }
        replay_data["version"] = ARCHIVE_VERSION
    for entry in cast("list[object]", replay_data["commands"]):
        _require_command(cast("Mapping[str, object]", entry), registry, handlers)
    document = _build_document(
        replay_data,
        registry,
        archive_version=archive_version,
        document_type=document_type,
    )
    bus = CommandBus(document, registry, kernel, handlers)
    # Spec-mandated one-shot rebuild on open; the getattr bridge mirrors
    # bus.py's pattern for crossing pyright-protected members.
    rebuild = cast("Callable[[], None]", getattr(bus, "_rebuild"))  # noqa: B009
    rebuild()
    return LoadedDocument(document=document, bus=bus)
