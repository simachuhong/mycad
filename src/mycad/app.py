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

from collections.abc import Sequence
from dataclasses import dataclass

from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
from mycad.commands.registry import CommandRegistry
from mycad.core.bus import CommandBus
from mycad.core.document import Document
from mycad.core.handlers import BuiltinModelingHandler, CommandHandler
from mycad.core.persistence import LoadedDocument
from mycad.formats.providers import STEP_PROVIDER, STL_PROVIDER
from mycad.formats.registry import FormatProviderRegistry
from mycad.geom.kernel import BuildKernel
from mycad.plugins.discovery import EntryPointDiscoverer
from mycad.plugins.loader import register_plugins
from mycad.plugins.manager import PluginManager
from mycad.plugins.types import DiscoveredPlugin, PluginDiscoverer

__all__ = ["AppServices", "build_app", "new_document"]


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
    formats = FormatProviderRegistry([STEP_PROVIDER, STL_PROVIDER])
    discovered: tuple[DiscoveredPlugin, ...] = ()
    for discoverer in discoverers:
        discovered += tuple(discoverer.discover())
    loaded = register_plugins(registry, formats, discovered)
    plugins = PluginManager(loaded)
    return AppServices(registry=registry, kernel=kernel, formats=formats, plugins=plugins)


def _handler_map(registry: CommandRegistry, plugins: PluginManager) -> dict[str, CommandHandler]:
    """Assemble the per-document handler map from the registry and plugins.

    Every registered builtin gets one ``BuiltinModelingHandler`` per
    command id (the T6 dispatch rule). Plugin contributions then
    overlay: a non-None ``handler_factory`` supplies the plugin's own
    handler, while a None factory falls back to a
    ``BuiltinModelingHandler`` — third-party-declared ordinary modeling
    commands execute through the builtin path.
    """
    handlers: dict[str, CommandHandler] = {
        spec.id: BuiltinModelingHandler(spec.id)
        for group in registry.list_by_category().values()
        for spec in group
    }
    for contribution in plugins.command_contributions():
        if contribution.handler_factory is not None:
            handlers[contribution.spec.id] = contribution.handler_factory()
        else:
            handlers[contribution.spec.id] = BuiltinModelingHandler(contribution.spec.id)
    return handlers


def new_document(services: AppServices, *, confirmed_by: str | None = None) -> LoadedDocument:
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
    document = Document(services.registry)
    bus = CommandBus(document, services.registry, services.kernel, handlers)
    services.kernel.reset()
    return LoadedDocument(document=document, bus=bus)
