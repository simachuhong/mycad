# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Loader tests (T9b): per-entry conflict isolation and app wiring.

Every scenario runs purely in-process (zero installs, zero pip). The
conflict fixture tree is imported through the conftest sys.path
injection. Skip codes never appear in this file's docstrings;
assertions compare against get_args-derived constants.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast, get_args

import pytest

from mycad import app as app_module
from mycad.builtin_commands import BUILTIN_COMMAND_SPECS
from mycad.commands.registry import CommandRegistry
from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.core.exceptions import ProviderConflictError
from mycad.core.handlers import BuiltinModelingHandler, CommandHandler, HandlerContext
from mycad.core.ports import ExportableKernel
from mycad.formats.base import FormatProvider
from mycad.formats.registry import FormatProviderRegistry
from mycad.plugins.discovery import EntryPointDiscoverer
from mycad.plugins.loader import register_plugins
from mycad.plugins.manager import PluginManager
from mycad.plugins.types import (
    WARNING_REASON,
    CommandContribution,
    DiscoveredPlugin,
    PluginManifest,
)

REASONS: tuple[str, ...] = get_args(WARNING_REASON)
COMMAND_CONFLICT: str = REASONS[3]
PROVIDER_CONFLICT: str = REASONS[4]

#: getattr bridge (repo pattern, cf. bus.py): direct import of the private
#: assembler trips reportPrivateUsage; pyright-ignore comments are banned.
_handler_map = cast(
    "Callable[[CommandRegistry, PluginManager], dict[str, CommandHandler]]",
    getattr(app_module, "_handler_map"),  # noqa: B009
)
build_app = app_module.build_app
new_document = app_module.new_document


def _spec(command_id: str) -> CommandSpec:
    """Self-made spec: unique id, zero-parameter schema, last-segment verb."""
    return CommandSpec(
        id=command_id,
        version=1,
        summary_en=f"Fake command {command_id}",
        label_zh="伪命令",
        params_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        cli=CliSyntax((command_id.split(".")[-1],)),
    )


def _contribution(command_id: str) -> CommandContribution:
    """A None-factory contribution for ``command_id``."""
    return CommandContribution(spec=_spec(command_id), handler_factory=None)


def _write_noop(geometry: ExportableKernel, path: Path) -> None:
    path.write_text("t9b\n", encoding="utf-8")


def _provider(
    name: str,
    *,
    priority: int = 50,
    extensions: tuple[str, ...] = (".t9b",),
) -> FormatProvider:
    """Self-made provider with all eight fields, .t9b by default."""
    return FormatProvider(
        name=name,
        vendor="t9b",
        priority=priority,
        extensions=extensions,
        can_read=False,
        can_write=True,
        target="shape",
        _writer=_write_noop,
    )


def _plugin(
    distribution_name: str,
    commands: tuple[CommandContribution, ...] = (),
    formats: tuple[FormatProvider, ...] = (),
    warnings: tuple[str, ...] = (),
) -> DiscoveredPlugin:
    """Hand-built DiscoveredPlugin with a well-formed manifest."""
    return DiscoveredPlugin(
        distribution_name=distribution_name,
        entrypoint=(),
        manifest=PluginManifest(id=distribution_name, version="1.0.0", api_version="1.0"),
        commands=commands,
        formats=formats,
        warnings=warnings,
    )


def _conflict_plugin() -> DiscoveredPlugin:
    """DiscoveredPlugin mirroring the conflict fixture tree's contributions."""
    module = importlib.import_module("mycad_plugin_conflict")
    return _plugin(
        "mycad-plugin-conflict",
        commands=tuple(module.commands()),
        formats=tuple(module.formats()),
    )


def test_conflicting_command_entry_skipped_builtin_kept(
    plugin_fixture_path: None,
) -> None:
    """A command colliding with a registered builtin drops only that entry."""
    registry = CommandRegistry()
    builtin_box = next(spec for spec in BUILTIN_COMMAND_SPECS if spec.id == "feature.box")
    registry.register(builtin_box)
    loaded = register_plugins(registry, FormatProviderRegistry(), (_conflict_plugin(),))
    assert len(loaded) == 1
    assert loaded[0].commands == ()
    assert loaded[0].warnings == (COMMAND_CONFLICT,)
    assert registry.get("feature.box") is builtin_box


def test_provider_conflict_skips_entry_error_carries_vendors(
    plugin_fixture_path: None,
) -> None:
    """A same-priority extension clash drops only the provider entry; the
    raised error (not the warning code) carries both name/vendor tuples.
    """
    formats_registry = FormatProviderRegistry(
        [_provider("TXT-PRE", priority=100, extensions=(".txt",))]
    )
    loaded = register_plugins(CommandRegistry(), formats_registry, (_conflict_plugin(),))
    assert loaded[0].formats == ()
    assert loaded[0].warnings == (PROVIDER_CONFLICT,)
    assert [p.name for p in formats_registry.list_providers()] == ["TXT-PRE"]
    fixture_provider = _conflict_plugin().formats[0]
    with pytest.raises(ProviderConflictError) as excinfo:
        formats_registry.register(fixture_provider)
    assert excinfo.value.extension == ".txt"
    assert excinfo.value.provider1 == ("TXT-PRE", "t9b")
    assert excinfo.value.provider2 == ("TXT-FIXTURE", "fixture")


def test_conflict_does_not_skip_remaining_plugin_entries() -> None:
    """One colliding command leaves the plugin's other command alive."""
    registry = CommandRegistry()
    registry.register(_spec("feature.box"))
    plugin = _plugin(
        "mix",
        commands=(_contribution("feature.box"), _contribution("mix.ok")),
    )
    loaded = register_plugins(registry, FormatProviderRegistry(), (plugin,))
    assert [c.spec.id for c in loaded[0].commands] == ["mix.ok"]
    assert loaded[0].warnings == (COMMAND_CONFLICT,)
    assert registry.get("mix.ok").id == "mix.ok"


def test_clean_load_records_no_warnings() -> None:
    """A conflict-free plugin loads with empty warnings and both entries alive."""
    provider = _provider("T9B-OK")
    plugin = _plugin(
        "clean",
        commands=(_contribution("demo.unique"),),
        formats=(provider,),
    )
    registry = CommandRegistry()
    formats_registry = FormatProviderRegistry()
    loaded = register_plugins(registry, formats_registry, (plugin,))
    assert loaded[0].warnings == ()
    assert [c.spec.id for c in loaded[0].commands] == ["demo.unique"]
    assert loaded[0].formats == (provider,)
    assert formats_registry.list_providers() == (provider,)


def test_duplicate_conflict_codes_deduplicated() -> None:
    """Two colliding entries recording the same code yield one warning."""
    registry = CommandRegistry()
    registry.register(_spec("demo.dup"))
    plugin = _plugin("dup", commands=(_contribution("demo.dup"), _contribution("demo.dup")))
    loaded = register_plugins(registry, FormatProviderRegistry(), (plugin,))
    assert loaded[0].commands == ()
    assert loaded[0].warnings == (COMMAND_CONFLICT,)


def test_result_feeds_plugin_manager() -> None:
    """The returned tuple is valid PluginManager input for loaded()/contributions."""
    plugin = _plugin("feedable", commands=(_contribution("demo.feed"),))
    manager = PluginManager(
        register_plugins(CommandRegistry(), FormatProviderRegistry(), (plugin,))
    )
    assert [p.distribution_name for p in manager.loaded()] == ["feedable"]
    assert [c.spec.id for c in manager.command_contributions()] == ["demo.feed"]


class _FakeHandler:
    """Structural CommandHandler used for factory-priority assertions."""

    def __init__(self, command_id: str) -> None:
        self.command_id = command_id

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
        return None


def test_handler_map_falls_back_to_builtin_for_none_factory() -> None:
    """A None handler_factory gets the BuiltinModelingHandler fallback."""
    spec = _spec("demo.fallback")
    registry = CommandRegistry()
    registry.register(spec)
    manager = PluginManager((_plugin("fb", commands=(_contribution("demo.fallback"),)),))
    handlers = _handler_map(registry, manager)
    assert isinstance(handlers["demo.fallback"], BuiltinModelingHandler)
    assert handlers["demo.fallback"].command_id == "demo.fallback"


def test_handler_map_prefers_plugin_factory() -> None:
    """A non-None factory wins over the fallback; the exact instance is used."""
    registry = CommandRegistry()
    registry.register(_spec("demo.factory"))
    handler = _FakeHandler("demo.factory")

    def factory() -> _FakeHandler:
        return handler

    contribution = CommandContribution(spec=_spec("demo.factory"), handler_factory=factory)
    manager = PluginManager((_plugin("fac", commands=(contribution,)),))
    handlers = _handler_map(registry, manager)
    assert handlers["demo.factory"] is handler


def test_handler_map_covers_all_builtin_commands() -> None:
    """With no plugins the map holds exactly one builtin handler per command."""
    registry = CommandRegistry()
    for spec in BUILTIN_COMMAND_SPECS:
        registry.register(spec)
    handlers = _handler_map(registry, PluginManager())
    assert set(handlers) == {spec.id for spec in BUILTIN_COMMAND_SPECS}
    assert len(handlers) == 8
    assert all(isinstance(h, BuiltinModelingHandler) for h in handlers.values())


def test_build_app_none_uses_default_discoverer(monkeypatch: pytest.MonkeyPatch) -> None:
    """None builds the real entry-point discoverer (empty environment here)."""
    calls: list[str] = []

    def _fake_discover(self: EntryPointDiscoverer) -> tuple[DiscoveredPlugin, ...]:
        calls.append("discover")
        return ()

    monkeypatch.setattr(EntryPointDiscoverer, "discover", _fake_discover)
    services = build_app(None)
    assert calls == ["discover"]
    assert sum(len(group) for group in services.registry.list_by_category().values()) == 8


def test_build_app_empty_list_runs_no_discoverer(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit empty discoverer sequence runs no discoverer at all."""
    calls: list[str] = []

    def _fake_discover(self: EntryPointDiscoverer) -> tuple[DiscoveredPlugin, ...]:
        calls.append("discover")
        return ()

    monkeypatch.setattr(EntryPointDiscoverer, "discover", _fake_discover)
    build_app([])
    assert calls == []


class _FakeDiscoverer:
    """Discoverer yielding one prebuilt plugin (structural protocol match)."""

    def __init__(self, plugin: DiscoveredPlugin) -> None:
        self._plugin = plugin

    def discover(self) -> tuple[DiscoveredPlugin, ...]:
        return (self._plugin,)


def test_multiple_discoverers_chained() -> None:
    """Two discoverers' results are concatenated into one manager."""
    first = _plugin("chain-one", commands=(_contribution("chain.one"),))
    second = _plugin("chain-two", commands=(_contribution("chain.two"),))
    services = build_app([_FakeDiscoverer(first), _FakeDiscoverer(second)])
    names = [p.distribution_name for p in services.plugins.discovered_plugins]
    assert names == ["chain-one", "chain-two"]
    assert services.registry.get("chain.one").id == "chain.one"
    assert services.registry.get("chain.two").id == "chain.two"


def test_register_plugins_is_pure() -> None:
    """The input tuple and its elements are never mutated by the loader."""
    registry = CommandRegistry()
    registry.register(_spec("feature.box"))
    original = _plugin(
        "pure",
        commands=(_contribution("feature.box"), _contribution("pure.ok")),
        formats=(_provider("PURE-FMT"),),
    )
    result = register_plugins(registry, FormatProviderRegistry(), (original,))
    assert result[0] is not original
    assert [c.spec.id for c in original.commands] == ["feature.box", "pure.ok"]
    assert [p.name for p in original.formats] == ["PURE-FMT"]
    assert original.warnings == ()
    assert [c.spec.id for c in result[0].commands] == ["pure.ok"]


def test_signal_listener_exception_is_isolated() -> None:
    """A raising pre_command listener neither aborts the command nor blocks
    the other listener (integration-level signal-hook check).
    """
    services = build_app([])
    loaded_doc = new_document(services)
    received: list[object] = []

    def _boom(payload: Mapping[str, object]) -> None:
        raise RuntimeError("listener boom")

    def _count(payload: Mapping[str, object]) -> None:
        received.append(payload.get("command_id"))

    loaded_doc.document.events.subscribe("pre_command", _boom)
    loaded_doc.document.events.subscribe("pre_command", _count)
    with pytest.warns(RuntimeWarning):
        result = loaded_doc.bus.execute(
            "feature.box", {"size_x": 1.0, "size_y": 1.0, "size_z": 1.0}
        )
    assert result is None
    assert received == ["feature.box"]
    assert len(loaded_doc.document.commands) == 1
