# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Composition root (T7c): the single place that knows every concrete type.

``build_app`` assembles the whole object graph — registry with the eight
built-in command specs, a geometry kernel, the format-provider registry and
the plugin manager. Desktop document sessions fork services so each editable
document owns its kernel; immutable registrations are shared.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast
from uuid import uuid4

from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
from mycad.commands.registry import CommandRegistry
from mycad.core.bus import CommandBus
from mycad.core.document import Document, ExecutedCommand
from mycad.core.document_kinds import DocumentKind, DocumentType, native_suffix
from mycad.core.document_migration import migrate_archive
from mycad.core.document_references import archive_fingerprint
from mycad.core.exceptions import ValidationError
from mycad.core.handlers import BuiltinModelingHandler, CommandHandler
from mycad.core.identity import BodyId, TopologyId
from mycad.core.persistence import LoadedDocument, document_payload, load_document_payload
from mycad.core.persistence import open_document as _open_document
from mycad.core.sketch import new_sketch_identity
from mycad.core.viewport_protocol import PlanarFaceFrame, ViewportData, ViewportSketchData
from mycad.formats.providers import DXF_PROVIDER, STEP_PROVIDER, STL_PROVIDER
from mycad.formats.registry import FormatProviderRegistry
from mycad.geom.drawing_worker import DrawingProjectionWorker
from mycad.geom.kernel import BuildKernel
from mycad.plugins.discovery import EntryPointDiscoverer
from mycad.plugins.loader import register_plugins
from mycad.plugins.manager import PluginManager
from mycad.plugins.types import DiscoveredPlugin, PluginDiscoverer

__all__ = [
    "AppServices",
    "build_app",
    "new_document",
    "open_app_document",
    "fork_app_services",
    "new_workspace_document",
    "open_session_documents",
    "open_session_bundle",
    "reference_parameters",
    "archive_plugin_identities",
    "preview_command",
    "preview_command_with_sketches",
    "interactive_selectors",
    "interactive_body_selectors",
]


@dataclass(frozen=True)
class AppServices:
    """Immutable service container assembled by ``build_app``.

    Exactly four members (pinned by contract): the command registry, the
    shared geometry kernel, the format-provider registry and the plugin
    manager. ``Document``/``CommandBus`` deliberately stay out — documents
    have a new/open lifecycle owned by the factory functions below.
    """

    registry: CommandRegistry
    kernel: BuildKernel
    formats: FormatProviderRegistry
    plugins: PluginManager


def build_app(discoverers: Sequence[PluginDiscoverer] | None = None) -> AppServices:
    """Assemble the application services (the layering exception in person).

    The eight built-in commands are registered by explicit Python calls —
    never via entry_points (that group is reserved for third-party
    plugins). ``discoverers`` selects the discovery source: ``None``
    builds the default entry-point discoverer (real third-party
    discovery), an explicit empty sequence disables discovery entirely,
    and any given discoverers are chained in order; the chained results
    go through the loader (per-entry conflict isolation) before the
    plugin manager is built.
    """
    discoverers = (EntryPointDiscoverer(),) if discoverers is None else tuple(discoverers)
    registry = CommandRegistry(schema_defs=COMMAND_SCHEMA_DEFS)
    for spec in BUILTIN_COMMAND_SPECS:
        registry.register(spec)
    kernel = BuildKernel()
    formats = FormatProviderRegistry([STEP_PROVIDER, STL_PROVIDER, DXF_PROVIDER])
    discovered: tuple[DiscoveredPlugin, ...] = ()
    for discoverer in discoverers:
        discovered += tuple(discoverer.discover())
    loaded = register_plugins(registry, formats, discovered)
    plugins = PluginManager(loaded)
    _configure_reference_loader(kernel, registry, plugins)
    return AppServices(registry=registry, kernel=kernel, formats=formats, plugins=plugins)


def handlers_for(services: AppServices) -> dict[tuple[str, int], CommandHandler]:
    """Public forwarding entry for ``_handler_map`` (phase-1 UI same-source consumption).

    The private bridge is consumed by the CLI via getattr (with an acknowledgment
    comment); the UI is prohibited from adding another granting comment, so this
    opens a public re-export — the assembly source of truth is still only this function.
    """
    return _handler_map(services.registry, services.plugins)


def archive_plugin_identities(
    services: AppServices,
) -> dict[tuple[str, int], dict[str, str]]:
    """Return package/API provenance for commands contributed by loaded plugins."""
    identities: dict[tuple[str, int], dict[str, str]] = {}
    for plugin in services.plugins.loaded():
        manifest = plugin.manifest
        if manifest is None:
            continue
        for contribution in plugin.commands:
            identities[(contribution.spec.id, contribution.spec.version)] = {
                "distribution": plugin.distribution_name or "unavailable",
                "plugin_id": manifest.id or "unavailable",
                "plugin_version": manifest.version or "unavailable",
                "api_version": manifest.api_version or "unavailable",
            }
    return identities


def _handler_map(
    registry: CommandRegistry, plugins: PluginManager
) -> dict[tuple[str, int], CommandHandler]:
    """Assemble the per-document handler map from the registry and plugins.

    Every registered builtin gets one ``BuiltinModelingHandler`` per
    command id (the T6 dispatch rule). Plugin contributions then
    overlay: a non-None ``handler_factory`` supplies the plugin's own
    handler, while a None factory falls back to a
    ``BuiltinModelingHandler`` — third-party-declared ordinary modeling
    commands execute through the builtin path.
    """
    handlers: dict[tuple[str, int], CommandHandler] = {
        (spec.id, spec.version): BuiltinModelingHandler(spec.id, spec.version)
        for spec in registry.all_specs()
    }
    for contribution in plugins.command_contributions():
        key = (contribution.spec.id, contribution.spec.version)
        if contribution.handler_factory is not None:
            handlers[key] = contribution.handler_factory()
        else:
            handlers[key] = BuiltinModelingHandler(*key)
    return handlers


def new_document(
    services: AppServices,
    *,
    confirmed_by: str | None = None,
    document_type: DocumentType = "part",
) -> LoadedDocument:
    """Build a fresh ``Document``/``CommandBus`` pair from shared services.

    The handler map is assembled here (not in ``build_app``) so plugin
    command contributions registered after startup are picked up by every
    new document. The shared kernel is reset exactly once, after the bus
    is assembled and before returning, so the new document starts from
    empty geometry without relying on caller discipline. ``confirmed_by``
    is a forward parameter: the phase-0 Document constructor takes no such
    argument (it rides on individual executed commands instead), so it is
    accepted and unused until a later phase wires it.
    """
    handlers = _handler_map(services.registry, services.plugins)
    document = Document(
        services.registry,
        archive_version=3 if document_type == "drawing2d" else 1,
        document_type=document_type,
    )
    bus = CommandBus(document, services.registry, services.kernel, handlers)
    services.kernel.reset()
    return LoadedDocument(document=document, bus=bus)


def fork_app_services(services: AppServices) -> AppServices:
    """Share immutable registrations while isolating all mutable geometry."""
    kernel = BuildKernel()
    _configure_reference_loader(kernel, services.registry, services.plugins)
    return AppServices(services.registry, kernel, services.formats, services.plugins)


def _configure_reference_loader(
    kernel: BuildKernel,
    registry: CommandRegistry,
    plugins: PluginManager,
) -> None:
    def replay(archive: Mapping[str, object]) -> BuildKernel:
        candidate = BuildKernel()
        _configure_reference_loader(candidate, registry, plugins)
        load_document_payload(
            dict(archive),
            registry=registry,
            kernel=candidate,
            handlers=_handler_map(registry, plugins),
        )
        return candidate

    kernel.set_reference_loader(replay)


def reference_parameters(
    source: Document,
    *,
    object_id: str = "",
    path: str = "",
    reference_id: str | None = None,
) -> dict[str, object]:
    archive = document_payload(source)
    return {
        "reference_id": reference_id or uuid4().hex,
        "file_id": source.file_id,
        "kind": source.document_kind,
        "path": path,
        "object_id": object_id,
        "fingerprint": archive_fingerprint(archive),
        "archive": archive,
    }


def copy_app_document(
    services: AppServices, source: Document
) -> tuple[AppServices, LoadedDocument]:
    """Prepare an identity-only replacement for the owning session entry.

    No geometry changes: the old editable entry is replaced only after the
    copy is written. It must not be added as a second entry sharing this kernel.
    """
    document = Document(
        services.registry,
        metadata=source.metadata_snapshot(),
        commands=source.commands,
        named_groups=source.named_groups,
        archive_version=4,
        document_type=source.document_type,
        document_kind=source.document_kind,
        file_id=uuid4().hex,
        migration_origin=source.migration_origin,
        reference_locations=source.reference_locations,
    )
    return services, LoadedDocument(
        document, CommandBus(document, services.registry, services.kernel, handlers_for(services))
    )


@dataclass(frozen=True)
class SessionOpenResult:
    documents: tuple[tuple[AppServices, LoadedDocument], ...]
    migrated: bool
    reference_messages: tuple[str, ...] = ()


def reference_association_status(
    services: AppServices,
    loaded: LoadedDocument,
    path: Path | None,
    *,
    locations: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Inspect locators without adopting external geometry or changing history."""
    messages: list[str] = []
    for reference in services.kernel.document_references:
        locators = loaded.document.reference_locations if locations is None else locations
        locator = locators.get(reference.file_id, reference.path)
        source_path = Path(locator) if locator else None
        if source_path is not None and not source_path.is_absolute():
            source_path = path.parent / source_path if path is not None else None
        label = Path(locator).name if locator else reference.file_id[:8]
        if source_path is None:
            state = "尚未定位"
        else:
            try:
                root: object = json.loads(source_path.read_text(encoding="utf-8"))
                if not isinstance(root, dict):
                    state = "源文件无效"
                elif cast("dict[str, object]", root).get("file_id") != reference.file_id:
                    state = "身份不匹配"
                elif cast("dict[str, object]", root).get("document_kind") != reference.kind:
                    state = "种类不匹配"
                else:
                    state = "关联有效"
            except FileNotFoundError:
                state = "来源文件缺失"
            except (OSError, ValueError):
                state = "来源无法读取"
        messages.append(f"{label}：{state}；当前使用已保存的采用版本。")
    return tuple(messages)


def separate_internal_sketch(
    services: AppServices, sketch_id: str
) -> tuple[AppServices, LoadedDocument]:
    """Copy a confirmed internal sketch to an independent editable document."""
    linked_ids = {r.reference_id for r in services.kernel.document_references if r.kind == "sketch"}
    if sketch_id in linked_ids:
        raise ValidationError("请先解除来源关联，再分离为独立二维文档。")
    sketch = next((s for s in services.kernel.sketches if s.sketch_id == sketch_id), None)
    if sketch is None:
        raise ValidationError("找不到已完成的内部草图。")
    isolated = fork_app_services(services)
    loaded = new_workspace_document(isolated, kind="sketch")
    detached = replace(sketch, sketch_id=new_sketch_identity(), support_face=None)
    loaded.bus.execute("sketch.create", detached.to_mapping(version=3), "local")
    return isolated, loaded


def open_session_bundle(services: AppServices, path: Path) -> SessionOpenResult:
    if path.suffix.lower() == ".masm":
        from mycad.core.exceptions import ValidationError

        raise ValidationError(".masm 装配文档尚未实现。")
    candidate_services = fork_app_services(services)
    original = open_app_document(candidate_services, path)
    if original.document.archive_version >= 4:
        from mycad.core.document_kinds import native_suffix
        from mycad.core.exceptions import ValidationError

        if path.suffix.lower() in (".my2d", ".my3d") and path.suffix.lower() != native_suffix(
            original.document.document_kind
        ):
            raise ValidationError("native suffix does not match document kind")
        return SessionOpenResult(
            ((candidate_services, original),),
            migrated=False,
            reference_messages=reference_association_status(candidate_services, original, path),
        )
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("archive must be an object")
    provenance = document_payload(
        new_workspace_document(fork_app_services(services), kind="part").document
    )["provenance"]
    candidates: list[tuple[AppServices, LoadedDocument]] = []
    for payload in migrate_archive(cast("dict[str, object]", raw), provenance):
        isolated = fork_app_services(services)
        loaded = load_document_payload(
            payload,
            registry=services.registry,
            kernel=isolated.kernel,
            handlers=handlers_for(isolated),
        )
        candidates.append((isolated, loaded))
    return SessionOpenResult(tuple(candidates), migrated=True)


def open_session_documents(
    services: AppServices, path: Path
) -> tuple[tuple[AppServices, LoadedDocument], ...]:
    return open_session_bundle(services, path).documents


def new_workspace_document(services: AppServices, *, kind: DocumentKind) -> LoadedDocument:
    document = Document(
        services.registry,
        archive_version=4,
        document_kind=kind,
        document_type="part" if kind == "part" else "drawing2d",
    )
    bus = CommandBus(document, services.registry, services.kernel, handlers_for(services))
    services.kernel.reset()
    return LoadedDocument(document, bus)


def open_app_document(services: AppServices, path: Path) -> LoadedDocument:
    """Open an archive with isolated replay, then commit its geometry once.

    ``core.persistence.open_document`` deliberately operates on the kernel it
    receives. Give it a fresh candidate so malformed or unreplayable archives
    cannot reset or partially overwrite the currently bound application
    kernel. Only after parsing, validation, and full replay succeed do we
    prepare the active bus and transfer the finished geometry into the stable
    service kernel.
    """
    if path.suffix.lower() == ".masm":
        raise ValidationError(".masm 装配文档尚未实现。")
    handlers = _handler_map(services.registry, services.plugins)
    candidate_kernel = BuildKernel()
    _configure_reference_loader(candidate_kernel, services.registry, services.plugins)
    candidate = _open_document(
        path,
        registry=services.registry,
        kernel=candidate_kernel,
        handlers=handlers,
    )
    if (
        candidate.document.archive_version >= 4
        and path.suffix.lower() in (".my2d", ".my3d")
        and path.suffix.lower() != native_suffix(candidate.document.document_kind)
    ):
        raise ValidationError("native suffix does not match document kind")
    active_bus = CommandBus(candidate.document, services.registry, services.kernel, handlers)
    services.kernel.replace_state_from(candidate_kernel)
    return LoadedDocument(document=candidate.document, bus=active_bus)


def interactive_selectors(
    services: AppServices,
    kind: str,
    topology_ids: Sequence[TopologyId],
) -> tuple[dict[str, object], ...]:
    """Translate runtime viewport picks into backend-neutral command locators."""

    if kind == "face":
        return tuple(
            services.kernel.interactive_face_selector(identity) for identity in topology_ids
        )
    if kind == "edge":
        return tuple(
            services.kernel.interactive_edge_selector(identity) for identity in topology_ids
        )
    raise ValueError(f"interactive modeling does not accept {kind!r} selections")


def interactive_body_selectors(
    services: AppServices, body_ids: Sequence[BodyId]
) -> tuple[dict[str, object], ...]:
    """Convert viewport body picks into replayable geometric selectors."""

    return tuple(services.kernel.interactive_body_selector(identity) for identity in body_ids)


def interactive_face_frame(services: AppServices, identity: TopologyId) -> PlanarFaceFrame:
    """Supply a neutral axis for the selected current face's pull handle."""
    return services.kernel.interactive_face_frame(identity)


def preview_command(
    services: AppServices,
    commands: Sequence[ExecutedCommand],
    command_id: str,
    params: Mapping[str, object],
) -> ViewportData:
    """Return the solid snapshot of an isolated candidate command."""
    return preview_command_with_sketches(services, commands, command_id, params)[0]


def preview_command_with_sketches(
    services: AppServices,
    commands: Sequence[ExecutedCommand],
    command_id: str,
    params: Mapping[str, object],
) -> tuple[ViewportData, tuple[ViewportSketchData, ...]]:
    """Replay a candidate command on an isolated document and kernel.

    The active application's kernel, Document, and CommandBus are never
    touched. The normal Bus pipeline validates parameters and calls only
    built-in handlers here; plugin handlers are excluded so a preview cannot
    run arbitrary extension code. All writes remain confined to the scratch
    document.
    """
    scratch_kernel = BuildKernel()
    _configure_reference_loader(scratch_kernel, services.registry, PluginManager(()))
    scratch_document = Document(services.registry)
    builtin_handlers = {
        (spec.id, spec.version): BuiltinModelingHandler(spec.id, spec.version)
        for spec in BUILTIN_COMMAND_SPECS
    }
    scratch_bus = CommandBus(
        scratch_document,
        services.registry,
        scratch_kernel,
        builtin_handlers,
    )
    for command in commands:
        if (command.id, command.version) not in builtin_handlers:
            raise ValueError(
                f"临时预览暂不支持重放非内置命令 {command.id!r}（历史序号 {command.ordinal}）"
            )
        scratch_bus.execute(
            command.id,
            command.params,
            command.confirmed_by,
            version=command.version,
        )
    scratch_bus.execute(command_id, params, confirmed_by="preview")
    snapshots = scratch_kernel.viewport_data()
    if not snapshots:
        raise ValueError("candidate command produced no viewport geometry")
    return snapshots[-1], scratch_kernel.sketch_display_data()


def create_drawing_worker() -> DrawingProjectionWorker:
    """Create an owned, explicitly closed background engineering projection service."""
    return DrawingProjectionWorker()
