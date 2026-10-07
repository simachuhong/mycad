# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Field-level lock of the plugin public contract (T7b).

Locks the frozen dataclass shapes, the skip-reason vocabulary and the
API constants defined in ``mycad.plugins.types`` (#round9-4/#round9-5),
plus two AST guards that keep the contract single-sourced. Docstring
discipline: this file never spells the six skip-reason codes in its
docstrings; the expected vocabulary lives only in the EXPECTED_...
constant below, and the codes themselves may appear in ``src/`` only
inside ``mycad/plugins/types.py``.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from typing import get_args

import pytest

from mycad.builtin_commands import BUILTIN_COMMAND_SPECS
from mycad.core.handlers import BuiltinModelingHandler
from mycad.plugins.types import (
    CURRENT_API_MAJOR,
    CURRENT_API_VERSION,
    WARNING_REASON,
    WARNING_REASONS,
    CommandContribution,
    DiscoveredPlugin,
    PluginDiscoverer,
    PluginManifest,
)

REPO = Path(__file__).resolve().parents[2]

#: The exhaustive skip-reason vocabulary (plan #round9-5). Kept in code,
#: never in docstrings, per the docstring discipline in the module docstring.
EXPECTED_WARNING_REASONS: frozenset[str] = frozenset(
    {
        "missing-manifest",
        "manifest-error",
        "incompatible-api",
        "command-conflict",
        "provider-conflict",
        "load-error",
    }
)


# ---------------------------------------------------------------------------
# frozen-dataclass field locks (order is part of the contract)
# ---------------------------------------------------------------------------


def test_discovered_plugin_fields_locked() -> None:
    names = tuple(field.name for field in dataclasses.fields(DiscoveredPlugin))
    assert names == (
        "distribution_name",
        "entrypoint",
        "manifest",
        "commands",
        "formats",
        "warnings",
    )


def test_plugin_manifest_fields_locked() -> None:
    names = tuple(field.name for field in dataclasses.fields(PluginManifest))
    assert names == ("id", "version", "api_version", "permissions", "homepage")


def test_command_contribution_fields_locked() -> None:
    names = tuple(field.name for field in dataclasses.fields(CommandContribution))
    assert names == ("spec", "handler_factory")


# ---------------------------------------------------------------------------
# vocabulary + constants
# ---------------------------------------------------------------------------


def test_warning_reason_vocabulary_locked() -> None:
    args = get_args(WARNING_REASON)
    assert len(args) == 6
    assert set(args) == EXPECTED_WARNING_REASONS
    assert WARNING_REASONS == frozenset(args)


def test_api_version_constants_locked() -> None:
    assert CURRENT_API_VERSION == "1.0"
    assert CURRENT_API_MAJOR == 1


# ---------------------------------------------------------------------------
# CommandContribution dual-form construction (#round9-4 acceptance)
# ---------------------------------------------------------------------------


def test_command_contribution_without_factory() -> None:
    spec = BUILTIN_COMMAND_SPECS[0]
    contribution = CommandContribution(spec=spec, handler_factory=None)
    assert contribution.spec is spec
    assert contribution.handler_factory is None


def test_command_contribution_with_zero_arg_factory() -> None:
    spec = BUILTIN_COMMAND_SPECS[0]
    contribution = CommandContribution(
        spec=spec, handler_factory=lambda: BuiltinModelingHandler(spec.id)
    )
    factory = contribution.handler_factory
    assert factory is not None
    handler = factory()
    assert isinstance(handler, BuiltinModelingHandler)
    assert handler.command_id == spec.id


def test_command_contribution_both_forms_are_frozen() -> None:
    spec = BUILTIN_COMMAND_SPECS[0]
    no_factory = CommandContribution(spec=spec, handler_factory=None)
    with_factory = CommandContribution(
        spec=spec, handler_factory=lambda: BuiltinModelingHandler(spec.id)
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        no_factory.__setattr__("spec", spec)
    with pytest.raises(dataclasses.FrozenInstanceError):
        with_factory.__setattr__("handler_factory", None)


# ---------------------------------------------------------------------------
# PluginDiscoverer protocol is structural (runtime_checkable)
# ---------------------------------------------------------------------------


class _MinimalDiscoverer:
    """Structurally satisfies PluginDiscoverer."""

    def discover(self) -> tuple[DiscoveredPlugin, ...]:
        return ()


class _NotADiscoverer:
    """Lacks discover — must fail the runtime protocol check."""


def test_plugin_discoverer_protocol_structural_probe() -> None:
    assert isinstance(_MinimalDiscoverer(), PluginDiscoverer)
    assert not isinstance(_NotADiscoverer(), PluginDiscoverer)


# ---------------------------------------------------------------------------
# AST guards: single definition site + reason-literal confinement
# ---------------------------------------------------------------------------


def test_command_contribution_single_definition_site() -> None:
    hits: list[str] = []
    for path in sorted((REPO / "src" / "mycad").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "CommandContribution":
                hits.append(path.relative_to(REPO).as_posix())
    assert hits == ["src/mycad/plugins/types.py"]


def test_reason_literals_confined_to_types() -> None:
    offenders: list[str] = []
    for path in sorted((REPO / "src" / "mycad").rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if rel == "src/mycad/plugins/types.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in EXPECTED_WARNING_REASONS:
                    offenders.append(f"{rel}: {node.value}")
    assert offenders == []
