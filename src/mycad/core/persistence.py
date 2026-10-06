# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Document persistence: atomic v1 JSON archive save/open (T6d).

Single-threaded document model (no write lock — phase 0 "Must NOT do").
Only core-side types and Protocols live here: registry, handlers and kernel
arrive as instances; ``CommandRegistry`` appears solely as a TYPE_CHECKING
annotation, so there is zero runtime import of ``mycad.commands``.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mycad.core.bus import CommandBus
from mycad.core.document import CommandAmendment, Document, ExecutedCommand
from mycad.core.exceptions import ArchiveVersionError, UnknownCommandError, ValidationError
from mycad.core.groups import NamedGroup
from mycad.core.handlers import CommandHandler
from mycad.core.kernel_protocol import Kernel
from mycad.core.migrations import migrate
from mycad.core.schema_v1 import (
    ARCHIVE_FORMAT,
    ARCHIVE_VERSION,
    selector_from_json,
    validate_archive,
)
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


def _archive_payload(document: Document) -> dict[str, object]:
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


def save_document(document: Document, path: Path) -> None:
    """Atomically write ``document`` as a v1 JSON archive to ``path``.

    Emits ``document_saving`` before and ``document_saved`` after the write.
    Atomicity is a same-directory temp file plus ``os.replace``; a missing
    parent directory propagates as ``OSError`` (never auto-created).
    """
    document.events.emit("document_saving", {"path": str(path)})
    text = json.dumps(_archive_payload(document), ensure_ascii=False, indent=2)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".tmp", delete=False, dir=path.parent, encoding="utf-8"
        ) as handle:
            handle.write(text)
            handle.flush()
            tmp_path = Path(handle.name)
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise
    document.events.emit("document_saved", {"path": str(path)})


def _require_command(
    entry: Mapping[str, object],
    registry: CommandRegistry,
    handlers: Mapping[str, CommandHandler],
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
    if command_id not in handlers:
        raise UnknownCommandError(
            f"archive command at ordinal {ordinal} ({command_id!r}) has no handler",
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


def _build_document(data: dict[str, object], registry: CommandRegistry) -> Document:
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
    )


def open_document(
    path: Path,
    *,
    registry: CommandRegistry,
    kernel: Kernel,
    handlers: Mapping[str, CommandHandler],
) -> LoadedDocument:
    """Read, validate, rebuild and assemble a document from ``path``.

    Pipeline (fixed order): read text -> parse JSON -> format check ->
    version check -> migrate (v1 identity) -> structural validation ->
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
    if version != ARCHIVE_VERSION:
        raise ArchiveVersionError(
            f"archive version {version!r} is not supported (expected {ARCHIVE_VERSION})",
            found=str(version),
            supported=ARCHIVE_VERSION,
        )
    migrated = cast("dict[str, object]", migrate(root))
    validate_archive(migrated)
    for entry in cast("list[object]", migrated["commands"]):
        _require_command(cast("Mapping[str, object]", entry), registry, handlers)
    document = _build_document(migrated, registry)
    bus = CommandBus(document, registry, kernel, handlers)
    # Spec-mandated one-shot rebuild on open; the getattr bridge mirrors
    # bus.py's pattern for crossing pyright-protected members.
    rebuild = cast("Callable[[], None]", getattr(bus, "_rebuild"))  # noqa: B009
    rebuild()
    return LoadedDocument(document=document, bus=bus)
