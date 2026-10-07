# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""EntryPointDiscoverer tests (T9a).

Every scenario except the real-environment probe monkeypatches
``importlib.metadata.entry_points`` with fakes built from hand-made
``EntryPoint`` objects (#round10-NB3: pure in-process, zero installs,
zero pip). Skip codes never appear in this file's docstrings;
assertions compare against get_args-derived constants.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from collections.abc import Callable
from typing import get_args

import pytest

from mycad.plugins.discovery import EntryPointDiscoverer
from mycad.plugins.manager import PluginManager
from mycad.plugins.types import WARNING_REASON

REASONS: tuple[str, ...] = get_args(WARNING_REASON)
MISSING_MANIFEST: str = REASONS[0]
DAMAGED_MANIFEST: str = REASONS[1]
API_MISMATCH: str = REASONS[2]
LOAD_FAILURE: str = REASONS[5]

COMMANDS = "mycad.commands"
FORMATS = "mycad.formats"


def _ep(name: str, value: str, group: str) -> importlib.metadata.EntryPoint:
    return importlib.metadata.EntryPoint(name=name, value=value, group=group)


def _fake(
    eps: dict[str, list[importlib.metadata.EntryPoint]],
) -> Callable[..., list[importlib.metadata.EntryPoint]]:
    def fake_entry_points(*, group: str) -> list[importlib.metadata.EntryPoint]:
        return list(eps.get(group, ()))

    return fake_entry_points


def _install_fake(
    monkeypatch: pytest.MonkeyPatch,
    eps: dict[str, list[importlib.metadata.EntryPoint]],
) -> None:
    monkeypatch.setattr(importlib.metadata, "entry_points", _fake(eps))


def test_manifest_dict_tree_discovered_via_module_name_fallback(
    monkeypatch: pytest.MonkeyPatch, plugin_fixture_path: None
) -> None:
    _install_fake(
        monkeypatch, {COMMANDS: [_ep("c", "mycad_plugin_manifest_dict:commands", COMMANDS)]}
    )
    plugins = EntryPointDiscoverer().discover()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.distribution_name == "mycad_plugin_manifest_dict"
    assert plugin.manifest is not None
    assert plugin.manifest.id == "manifest-dict"
    assert plugin.commands == ()
    assert plugin.formats == ()
    assert plugin.warnings == ()
    assert plugin.entrypoint == ("mycad.commands:mycad_plugin_manifest_dict:commands",)


def test_callable_tree_merges_both_groups_and_calls_manifest_once(
    monkeypatch: pytest.MonkeyPatch, plugin_fixture_path: None
) -> None:
    _install_fake(
        monkeypatch,
        {
            COMMANDS: [_ep("c", "mycad_plugin_manifest_callable:commands", COMMANDS)],
            FORMATS: [_ep("f", "mycad_plugin_manifest_callable:formats", FORMATS)],
        },
    )
    module = importlib.import_module("mycad_plugin_manifest_callable")
    before: int = module.CALL_COUNT[0]
    plugins = EntryPointDiscoverer().discover()
    after: int = module.CALL_COUNT[0]
    assert after - before == 1
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.distribution_name == "mycad_plugin_manifest_callable"
    assert plugin.entrypoint == (
        "mycad.commands:mycad_plugin_manifest_callable:commands",
        "mycad.formats:mycad_plugin_manifest_callable:formats",
    )
    assert plugin.manifest is not None
    assert plugin.manifest.id == "manifest-callable"
    assert [c.spec.id for c in plugin.commands] == ["demo.spec.1"]
    assert [f.name for f in plugin.formats] == ["FT1"]
    assert plugin.warnings == ()


def test_future_api_tree_skipped_with_api_code(
    monkeypatch: pytest.MonkeyPatch, plugin_fixture_path: None
) -> None:
    _install_fake(monkeypatch, {COMMANDS: [_ep("c", "mycad_plugin_future:commands", COMMANDS)]})
    plugins = EntryPointDiscoverer().discover()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.manifest is None
    assert plugin.commands == ()
    assert plugin.formats == ()
    assert plugin.warnings == (API_MISMATCH,)


@pytest.mark.parametrize(
    ("module_name", "expected_warning"),
    [
        ("mycad_plugin_bad.missing_attr", MISSING_MANIFEST),
        ("mycad_plugin_bad.bad_missing", DAMAGED_MANIFEST),
        ("mycad_plugin_bad.bad_extra", DAMAGED_MANIFEST),
        ("mycad_plugin_bad.bad_types", DAMAGED_MANIFEST),
        ("mycad_plugin_bad.bad_id", DAMAGED_MANIFEST),
    ],
)
def test_bad_submodules_skip_with_planned_warnings(
    monkeypatch: pytest.MonkeyPatch,
    plugin_fixture_path: None,
    module_name: str,
    expected_warning: str,
) -> None:
    _install_fake(monkeypatch, {COMMANDS: [_ep("b", f"{module_name}:commands", COMMANDS)]})
    plugins = EntryPointDiscoverer().discover()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.distribution_name == module_name
    assert plugin.manifest is None
    assert plugin.commands == ()
    assert plugin.formats == ()
    assert plugin.warnings == (expected_warning,)


@pytest.mark.parametrize(
    ("module_name", "loads"),
    [
        ("mycad_plugin_matrix.api_1_0", True),
        ("mycad_plugin_matrix.api_1_5", True),
        ("mycad_plugin_matrix.api_2_0", False),
        ("mycad_plugin_matrix.api_v1", False),
        ("mycad_plugin_matrix.api_abc", False),
    ],
)
def test_matrix_api_gate_through_discovery(
    monkeypatch: pytest.MonkeyPatch,
    plugin_fixture_path: None,
    module_name: str,
    loads: bool,
) -> None:
    _install_fake(monkeypatch, {COMMANDS: [_ep("m", f"{module_name}:commands", COMMANDS)]})
    plugins = EntryPointDiscoverer().discover()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.commands == ()
    if loads:
        assert plugin.manifest is not None
        assert plugin.warnings == ()
    else:
        assert plugin.manifest is None
        assert plugin.warnings == (API_MISMATCH,)


def test_formats_empty_factory_registers_nothing(
    monkeypatch: pytest.MonkeyPatch, plugin_fixture_path: None
) -> None:
    _install_fake(
        monkeypatch,
        {FORMATS: [_ep("f", "mycad_plugin_formats.empty_factory:formats", FORMATS)]},
    )
    plugins = EntryPointDiscoverer().discover()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.manifest is not None
    assert plugin.formats == ()
    assert plugin.warnings == ()


def test_raise_factory_drops_only_the_formats_group(
    monkeypatch: pytest.MonkeyPatch, plugin_fixture_path: None
) -> None:
    _install_fake(
        monkeypatch,
        {
            COMMANDS: [_ep("c", "mycad_plugin_formats.raise_factory:commands", COMMANDS)],
            FORMATS: [_ep("f", "mycad_plugin_formats.raise_factory:formats", FORMATS)],
        },
    )
    plugins = EntryPointDiscoverer().discover()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.manifest is not None
    assert [c.spec.id for c in plugin.commands] == ["formats.raise.spec.1"]
    assert plugin.formats == ()
    assert plugin.warnings == (LOAD_FAILURE,)


def test_formats_single_factory_yields_one_provider(
    monkeypatch: pytest.MonkeyPatch, plugin_fixture_path: None
) -> None:
    _install_fake(
        monkeypatch, {FORMATS: [_ep("f", "mycad_plugin_formats.single:formats", FORMATS)]}
    )
    plugins = EntryPointDiscoverer().discover()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.manifest is not None
    assert [f.name for f in plugin.formats] == ["SINGLE-FIXTURE"]
    assert plugin.warnings == ()


def test_non_callable_entry_attr_fails_the_group(
    monkeypatch: pytest.MonkeyPatch, plugin_fixture_path: None
) -> None:
    # The manifest dict attribute is a legal module member but not a
    # factory, so the entry contract rejects it.
    _install_fake(
        monkeypatch, {COMMANDS: [_ep("c", "mycad_plugin_manifest_dict:manifest", COMMANDS)]}
    )
    plugins = EntryPointDiscoverer().discover()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.manifest is not None
    assert plugin.commands == ()
    assert plugin.warnings == (LOAD_FAILURE,)


def test_entry_factory_returning_non_list_fails_the_group(
    monkeypatch: pytest.MonkeyPatch, plugin_fixture_path: None
) -> None:
    # The callable manifest builder returns a dict, not a list.
    _install_fake(
        monkeypatch,
        {COMMANDS: [_ep("c", "mycad_plugin_manifest_callable:manifest", COMMANDS)]},
    )
    plugins = EntryPointDiscoverer().discover()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.manifest is not None
    assert plugin.commands == ()
    assert plugin.warnings == (LOAD_FAILURE,)


def test_wrong_element_type_skips_the_whole_group(
    monkeypatch: pytest.MonkeyPatch, plugin_fixture_path: None
) -> None:
    # The "mixed" entry loads the conflict tree's formats factory into
    # the commands group: its list element has the wrong type, so the
    # entire commands group for this distribution is dropped —
    # including the healthy entry evaluated before it.
    _install_fake(
        monkeypatch,
        {
            COMMANDS: [
                _ep("good", "mycad_plugin_conflict:commands", COMMANDS),
                _ep("mixed", "mycad_plugin_conflict:formats", COMMANDS),
            ]
        },
    )
    plugins = EntryPointDiscoverer().discover()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.commands == ()
    assert plugin.warnings == (LOAD_FAILURE,)
    assert plugin.entrypoint == (
        "mycad.commands:mycad_plugin_conflict:commands",
        "mycad.commands:mycad_plugin_conflict:formats",
    )


def test_discovery_is_deterministic_across_runs(
    monkeypatch: pytest.MonkeyPatch, plugin_fixture_path: None
) -> None:
    _install_fake(
        monkeypatch,
        {
            COMMANDS: [
                _ep("c1", "mycad_plugin_manifest_dict:commands", COMMANDS),
                _ep("c2", "mycad_plugin_conflict:commands", COMMANDS),
            ],
            FORMATS: [
                _ep("f1", "mycad_plugin_formats.single:formats", FORMATS),
                _ep("f2", "mycad_plugin_conflict:formats", FORMATS),
            ],
        },
    )

    def projection() -> list[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]]:
        # Provider instances carry fresh writer closures per discovery
        # run, so equality is asserted on projected values only.
        return [
            (
                p.distribution_name,
                tuple(c.spec.id for c in p.commands),
                tuple(f.name for f in p.formats),
                p.warnings,
            )
            for p in EntryPointDiscoverer().discover()
        ]

    assert projection() == projection()
    assert len(projection()) == 3


def test_real_environment_has_no_plugin_entry_points() -> None:
    assert EntryPointDiscoverer().discover() == ()


def test_manager_views_exclude_manifest_none_plugins(
    monkeypatch: pytest.MonkeyPatch, plugin_fixture_path: None
) -> None:
    _install_fake(
        monkeypatch,
        {
            COMMANDS: [
                _ep("good", "mycad_plugin_manifest_dict:commands", COMMANDS),
                _ep("future", "mycad_plugin_future:commands", COMMANDS),
                _ep("broken", "mycad_plugin_bad.bad_missing:commands", COMMANDS),
            ],
        },
    )
    plugins = EntryPointDiscoverer().discover()
    manager = PluginManager(plugins)
    assert [p.distribution_name for p in manager.loaded()] == ["mycad_plugin_manifest_dict"]
    assert manager.skipped() == (
        ("mycad_plugin_bad.bad_missing", DAMAGED_MANIFEST),
        ("mycad_plugin_future", API_MISMATCH),
    )
