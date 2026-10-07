# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""PluginManager thin-view tests (T7b): empty construction, mixed fixture
views, list-to-tuple conversion and frozen-ness."""

from __future__ import annotations

import dataclasses

import pytest

from mycad.builtin_commands import BUILTIN_COMMAND_SPECS
from mycad.core.handlers import BuiltinModelingHandler
from mycad.formats.providers import STEP_PROVIDER
from mycad.plugins.manager import PluginManager
from mycad.plugins.types import CommandContribution, DiscoveredPlugin, PluginManifest


def _contribution() -> CommandContribution:
    spec = BUILTIN_COMMAND_SPECS[0]
    return CommandContribution(spec=spec, handler_factory=lambda: BuiltinModelingHandler(spec.id))


def _manifest(plugin_id: str) -> PluginManifest:
    return PluginManifest(id=plugin_id, version="0.1.0", api_version="1.0")


def _plugin_a() -> DiscoveredPlugin:
    """Loaded: manifest present, zero warnings, one command + one format."""

    return DiscoveredPlugin(
        distribution_name="A-dist",
        entrypoint=("mycad.commands:plugin_a:COMMANDS",),
        manifest=_manifest("plugin-a"),
        commands=(_contribution(),),
        formats=(STEP_PROVIDER,),
    )


def _plugin_b() -> DiscoveredPlugin:
    """Skipped: manifest None with one warning code."""

    return DiscoveredPlugin(
        distribution_name="B-dist",
        entrypoint=("mycad.commands:plugin_b:COMMANDS",),
        manifest=None,
        warnings=("incompatible-api",),
    )


def _plugin_c() -> DiscoveredPlugin:
    """Loaded but contributes nothing: manifest present, empty commands."""

    return DiscoveredPlugin(
        distribution_name="C-dist",
        entrypoint=(),
        manifest=_manifest("plugin-c"),
    )


def test_empty_manager_views() -> None:
    for manager in (PluginManager(()), PluginManager()):
        assert manager.discovered_plugins == ()
        assert manager.loaded() == ()
        assert manager.skipped() == ()
        assert manager.command_contributions() == ()
        assert manager.format_providers() == ()


def test_list_construction_converts_to_tuple() -> None:
    plugin_a = _plugin_a()
    manager = PluginManager(discovered=[plugin_a])
    assert manager.discovered_plugins == (plugin_a,)


def test_mixed_discovery_views() -> None:
    plugin_a = _plugin_a()
    manager = PluginManager((plugin_a, _plugin_b(), _plugin_c()))
    assert manager.loaded() == (plugin_a, _plugin_c())
    assert manager.skipped() == (("B-dist", "incompatible-api"),)
    assert manager.command_contributions() == plugin_a.commands
    assert manager.format_providers() == plugin_a.formats


def test_manager_is_frozen() -> None:
    manager = PluginManager((_plugin_a(),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        manager.__setattr__("discovered_plugins", ())
