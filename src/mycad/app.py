# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Composition root (T7c): the single place that knows every concrete type.

``build_app`` assembles the whole object graph — registry with the eight
built-in command specs, the shared geometry kernel, the format-provider
registry and the plugin manager — and ``new_document`` builds per-document
``Document``/``CommandBus`` pairs from those services. The kernel is a
process-wide singleton reused across documents: the factory owns the
``reset()`` call, so callers never rely on remembering it. Multi-document
kernel sessions are a Phase 1 direction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
from mycad.commands.registry import CommandRegistry
from mycad.core.bus import CommandBus
from mycad.core.document import Document, ExecutedCommand
from mycad.core.document_kinds import DocumentType
from mycad.core.handlers import BuiltinModelingHandler, CommandHandler
from mycad.core.identity import BodyId, TopologyId
from mycad.core.persistence import LoadedDocument
from mycad.core.persistence import open_document as _open_document
from mycad.core.viewport_protocol import PlanarFaceFrame, ViewportData, ViewportSketchData
from mycad.formats.providers import DXF_PROVIDER, STEP_PROVIDER, STL_PROVIDER
from mycad.formats.registry import FormatProviderRegistry
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


def open_app_document(services: AppServices, path: Path) -> LoadedDocument:
    """Open an archive with isolated replay, then commit its geometry once.

    ``core.persistence.open_document`` deliberately operates on the kernel it
    receives. Give it a fresh candidate so malformed or unreplayable archives
    cannot reset or partially overwrite the currently bound application
    kernel. Only after parsing, validation, and full replay succeed do we
    prepare the active bus and transfer the finished geometry into the stable
    service kernel.
    """
    handlers = _handler_map(services.registry, services.plugins)
    candidate_kernel = BuildKernel()
    candidate = _open_document(
        path,
        registry=services.registry,
        kernel=candidate_kernel,
        handlers=handlers,
    )
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
