# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Agent package surface lock + zero-network scan (T7b)."""

from __future__ import annotations

from pathlib import Path

import mycad.agent
from mycad import plugins

REPO = Path(__file__).resolve().parents[2]

#: B0 finding: every plan transition is a ``Plan`` method (no free
#: transition functions exist), so the agent re-export surface is the two
#: plan classes plus the transition exception. ``plan_types`` is the
#: submodule attribute Python's import system attaches to the package —
#: structural, not a re-exported symbol.
AGENT_PUBLIC_NAMES: set[str] = {"Plan", "PlannedCommand", "InvalidPlanTransition"}
AGENT_SUBMODULE_ARTIFACTS: set[str] = {"plan_types"}

#: The seven contract names re-exported by ``mycad.plugins`` (plan T7 +
#: T9a's discoverer), plus the ``types`` / ``manager`` / ``discovery`` /
#: ``manifest`` / ``loader`` submodule attributes the import system
#: attaches to the package (``loader`` is pre-listed for T9b, which
#: makes the assertion immune to import-order nondeterminism).
PLUGINS_PUBLIC_NAMES: set[str] = {
    "CURRENT_API_VERSION",
    "CommandContribution",
    "DiscoveredPlugin",
    "EntryPointDiscoverer",
    "PluginDiscoverer",
    "PluginManager",
    "PluginManifest",
}
PLUGINS_SUBMODULE_ARTIFACTS: set[str] = {"types", "manager", "discovery", "manifest", "loader"}

FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "import socket",
    "import http",
    "requests",
    "openai",
    "anthropic",
    "schema_catalog",
)


def test_agent_public_surface_is_plan_reexports_only() -> None:
    names = {name for name in dir(mycad.agent) if not name.startswith("_")}
    assert names - AGENT_SUBMODULE_ARTIFACTS == AGENT_PUBLIC_NAMES


def test_agent_package_has_no_network_or_llm_code() -> None:
    agent_files = sorted((REPO / "src" / "mycad" / "agent").glob("*.py"))
    assert agent_files, "agent package missing"
    for path in agent_files:
        text = path.read_text(encoding="utf-8").lower()
        for needle in FORBIDDEN_SUBSTRINGS:
            assert needle not in text, f"{path.relative_to(REPO)}: {needle!r} found"


def test_plugins_public_surface_is_exactly_seven_names() -> None:
    names = {name for name in dir(plugins) if not name.startswith("_")}
    assert names - PLUGINS_SUBMODULE_ARTIFACTS == PLUGINS_PUBLIC_NAMES
