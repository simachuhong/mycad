# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""``commands`` and ``plugins`` subcommands: the fixed eight-builtin listing
(discovery isolated) and the loaded/skipped plugin report (exit 0 always)."""

from __future__ import annotations

import json

import pytest

from mycad.app import build_app
from mycad.builtin_commands import BUILTIN_COMMAND_SPECS
from mycad.cli.__main__ import main
from mycad.cli.session import CliSession
from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.plugins.discovery import EntryPointDiscoverer
from mycad.plugins.types import (
    WARNING_REASONS,
    CommandContribution,
    DiscoveredPlugin,
    PluginManifest,
)

JSON_KEYS = {"verb", "id", "summary_en", "label_zh"}


class _FixedDiscoverer:
    """Stub discoverer: hands build_app a canned discovery result."""

    def __init__(self, plugins: tuple[DiscoveredPlugin, ...]) -> None:
        self._plugins = plugins

    def discover(self) -> tuple[DiscoveredPlugin, ...]:
        return self._plugins


def _demo_plugin() -> DiscoveredPlugin:
    spec = CommandSpec(
        id="demo.ping",
        version=1,
        summary_en="Ping the demo plugin",
        label_zh="Ping",
        params_schema={"type": "object", "properties": {}, "additionalProperties": False},
        cli=CliSyntax(verb_aliases=("demo.ping",)),
    )
    return DiscoveredPlugin(
        distribution_name="demo-dist",
        entrypoint=(),
        manifest=PluginManifest(id="demo", version="0.2.0", api_version="1.0"),
        commands=(CommandContribution(spec=spec, handler_factory=None),),
    )


def _skipped(name: str, warnings: tuple[str, ...] = ()) -> DiscoveredPlugin:
    return DiscoveredPlugin(distribution_name=name, entrypoint=(), manifest=None, warnings=warnings)


def _no_plugins(self: EntryPointDiscoverer) -> tuple[DiscoveredPlugin, ...]:
    return ()


def test_commands_lists_exactly_eight(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(EntryPointDiscoverer, "discover", _no_plugins)
    assert main(["commands"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 8
    rows = [line.split("\t") for line in lines]
    assert all(len(row) == 3 for row in rows)
    verbs = [row[0] for row in rows]
    assert verbs == sorted(verbs)
    assert verbs[0] == "box"
    assert verbs[-1] == "revolve"
    assert {row[1] for row in rows} == {spec.id for spec in BUILTIN_COMMAND_SPECS}


def test_commands_json_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(EntryPointDiscoverer, "discover", _no_plugins)
    assert main(["commands", "--json"]) == 0
    raw = capsys.readouterr().out
    payload = json.loads(raw)
    assert set(payload) == {"commands"}
    commands = payload["commands"]
    assert len(commands) == 8
    verbs = [entry["verb"] for entry in commands]
    assert verbs == sorted(verbs)
    for entry in commands:
        assert set(entry) == JSON_KEYS
    assert "\\\\u" not in raw  # ensure_ascii=False: label_zh stays readable
    assert any(ord(ch) > 127 for ch in raw)


def test_commands_lists_plugin_contributions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plugin-contributed command is visible to ``commands``, not just to the REPL.

    Driven through ``main`` on purpose: the subcommand must build the app
    with real discovery enabled, which a direct ``CliSession`` call cannot
    prove.
    """

    def _one_plugin(self: EntryPointDiscoverer) -> tuple[DiscoveredPlugin, ...]:
        return (_demo_plugin(),)

    monkeypatch.setattr(EntryPointDiscoverer, "discover", _one_plugin)
    assert main(["commands"]) == 0
    rows = [line.split("\t") for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 9
    assert "demo.ping" in {row[1] for row in rows}
    verbs = [row[0] for row in rows]
    assert verbs == sorted(verbs)


def test_commands_rejects_extra_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["commands", "extra"]) == 2
    assert "usage: mycad commands" in capsys.readouterr().err


def test_plugins_clean_environment_is_quiet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _no_plugins(self: EntryPointDiscoverer) -> tuple[DiscoveredPlugin, ...]:
        return ()

    monkeypatch.setattr(EntryPointDiscoverer, "discover", _no_plugins)
    assert main(["plugins"]) == 0
    assert capsys.readouterr().out == ""


def test_plugins_loaded_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    services = build_app(discoverers=[_FixedDiscoverer((_demo_plugin(),))])
    assert CliSession(services).list_plugins() == 0
    assert capsys.readouterr().out.splitlines() == [
        "loaded: demo v0.2.0 api=1.0 commands=1 formats=0"
    ]


@pytest.mark.parametrize(
    ("plugin", "line"),
    [
        (_skipped("ghost"), "skipped: ghost reason=missing-manifest"),
        (_skipped("future", ("incompatible-api",)), "skipped: future reason=incompatible-api"),
    ],
)
def test_plugins_skipped_lines_exit_zero(
    capsys: pytest.CaptureFixture[str], plugin: DiscoveredPlugin, line: str
) -> None:
    services = build_app(discoverers=[_FixedDiscoverer((plugin,))])
    assert CliSession(services).list_plugins() == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [line]
    assert line.split("reason=", 1)[1] in WARNING_REASONS


def test_plugins_lists_loaded_and_skipped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plugins = (_demo_plugin(), _skipped("ghost"))
    services = build_app(discoverers=[_FixedDiscoverer(plugins)])
    assert CliSession(services).list_plugins() == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "loaded: demo v0.2.0 api=1.0 commands=1 formats=0"
    assert out[1] == "skipped: ghost reason=missing-manifest"


def test_plugins_rejects_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["plugins", "--json"]) == 2
    assert "plugins takes no arguments" in capsys.readouterr().err
