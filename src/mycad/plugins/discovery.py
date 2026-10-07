# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Entry-point based plugin discovery (T9a).

Implements the T7 ``PluginDiscoverer`` protocol structurally: scan the
configured importlib.metadata entry groups, resolve each entry
module's manifest (memoized per module), evaluate the contribution
factories with per-group failure isolation, and merge everything into
one ``DiscoveredPlugin`` per distribution, sorted by distribution
name. Skip-reason codes are derived from the contract Literal, never
spelled out as literals here.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass, field
from typing import TypeGuard, get_args

from mycad.plugins.manifest import resolve_manifest
from mycad.plugins.types import (
    WARNING_REASON,
    CommandContribution,
    DiscoveredPlugin,
    FormatProvider,
    PluginManifest,
)

_COMMANDS_GROUP = "mycad.commands"
_FORMATS_GROUP = "mycad.formats"

#: Derived from the contract Literal (source order): the code recorded
#: when an entry breaks the contribution contract, and the ordering key
#: that keeps merged warnings in vocabulary order.
_LOAD_FAILURE: str = get_args(WARNING_REASON)[5]
_CODE_ORDER: dict[str, int] = {
    str(code): index for index, code in enumerate(get_args(WARNING_REASON))
}


@dataclass
class _Distribution:
    """Mutable per-distribution accumulator used while scanning groups.

    The manifest state is resolved once (first entry module wins) and
    every field is folded into one ``DiscoveredPlugin`` at the end.
    """

    entrypoints: set[str] = field(default_factory=set)
    manifest: PluginManifest | None = None
    manifest_warning: str | None = None
    manifest_resolved: bool = False
    commands: list[CommandContribution] = field(default_factory=list)
    command_group_failed: bool = False
    formats: list[FormatProvider] = field(default_factory=list)
    format_group_failed: bool = False
    warnings: set[str] = field(default_factory=set)

    def note_group_failure(self, group: str) -> None:
        """Mark one entry group as broken for this distribution."""
        self.warnings.add(_LOAD_FAILURE)
        if group == _COMMANDS_GROUP:
            self.command_group_failed = True
        elif group == _FORMATS_GROUP:
            self.format_group_failed = True


def _distribution_name(ep: importlib.metadata.EntryPoint) -> str:
    """Best-effort distribution name for one entry point.

    Entry points returned by a real ``entry_points()`` scan carry a
    ``Distribution`` whose metadata names them. Hand-constructed entry
    points (the pure in-process fixtures, and any EP built directly)
    always have ``dist = None``; those fall back to the entry's module
    name so callers can still predict the merged distribution identity
    (documented deviation, see the T9a evidence notes).
    """
    dist = ep.dist
    if dist is not None:
        # A missing Name header yields a falsy value at runtime, which
        # the truthiness check below routes to the module-name fallback.
        name = dist.metadata["Name"]
        if name:
            return name
    return ep.module


def _import_module(name: str) -> object | None:
    """Import a plugin module; None (never raising) when it cannot load."""

    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _is_list(value: object) -> TypeGuard[list[object]]:
    """Narrow ``object`` to a fully-typed list (isinstance alone yields Unknown)."""

    return isinstance(value, list)


def _element_ok(item: object, group: str) -> bool:
    """Type-check one factory result element against its group."""
    if group == _COMMANDS_GROUP:
        return isinstance(item, CommandContribution)
    if group == _FORMATS_GROUP:
        return isinstance(item, FormatProvider)
    # Phase 0 has exactly two contribution kinds; any other configured
    # group contributes entry-point references only, so its elements
    # are accepted but never stored.
    return True


def _evaluate_entry(ep: importlib.metadata.EntryPoint, group: str) -> list[object] | None:
    """Load one entry point and call its factory exactly once.

    Returns the validated element list, or None when the entry breaks
    the contribution contract (attr is not callable, the call raised,
    the return value is not a list, or any element has the wrong type
    for its group) — the caller then skips that whole group for the
    distribution and records the derived failure code.
    """
    try:
        attr: object = ep.load()
    except Exception:
        return None
    if not callable(attr):
        return None
    try:
        result: object = attr()
    except Exception:
        return None
    if not _is_list(result):
        return None
    for item in result:
        if not _element_ok(item, group):
            return None
    return list(result)


class EntryPointDiscoverer:
    """PluginDiscoverer over importlib.metadata entry-point groups."""

    def __init__(self, groups: tuple[str, ...] = (_COMMANDS_GROUP, _FORMATS_GROUP)) -> None:
        self._groups = groups

    def discover(self) -> tuple[DiscoveredPlugin, ...]:
        """Scan every configured group; one result per distribution.

        A broken manifest skips the distribution's entry evaluation
        entirely; a broken entry group drops only that group's
        contributions for its distribution. Results are sorted by
        distribution name for deterministic ordering.
        """
        states: dict[str, _Distribution] = {}
        manifest_cache: dict[object, tuple[PluginManifest | None, str | None]] = {}
        for group in self._groups:
            eps = importlib.metadata.entry_points(group=group)
            for ep in sorted(eps, key=lambda entry: (entry.name, entry.value)):
                state = states.setdefault(_distribution_name(ep), _Distribution())
                state.entrypoints.add(f"{group}:{ep.module}:{ep.attr}")
                module = _import_module(ep.module)
                if module is None:
                    state.note_group_failure(group)
                    continue
                if not state.manifest_resolved:
                    state.manifest_resolved = True
                    if module not in manifest_cache:
                        manifest_cache[module] = resolve_manifest(module)
                    state.manifest, state.manifest_warning = manifest_cache[module]
                    if state.manifest_warning is not None:
                        state.warnings.add(state.manifest_warning)
                if state.manifest_warning is not None:
                    continue
                items = _evaluate_entry(ep, group)
                if items is None:
                    state.note_group_failure(group)
                    continue
                if group == _COMMANDS_GROUP:
                    state.commands.extend(
                        item for item in items if isinstance(item, CommandContribution)
                    )
                elif group == _FORMATS_GROUP:
                    state.formats.extend(item for item in items if isinstance(item, FormatProvider))
        plugins: list[DiscoveredPlugin] = []
        for name in sorted(states):
            state = states[name]
            plugins.append(
                DiscoveredPlugin(
                    distribution_name=name,
                    entrypoint=tuple(sorted(state.entrypoints)),
                    manifest=state.manifest,
                    commands=() if state.command_group_failed else tuple(state.commands),
                    formats=() if state.format_group_failed else tuple(state.formats),
                    warnings=tuple(sorted(state.warnings, key=_CODE_ORDER.__getitem__)),
                )
            )
        return tuple(plugins)
