# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Thin views over discovery results (T7b).

The manager is a frozen wrapper: it holds what a discoverer found and
answers loaded/skipped/contribution queries. Phase-0 semantics are thin
on purpose — T9 wires real discovery results through the same
constructor (the construction signature is frozen by contract; T9 must
not change it).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import get_args

from mycad.plugins.types import (
    WARNING_REASON,
    CommandContribution,
    DiscoveredPlugin,
    FormatProvider,
)

# Skip-reason string literals may only live in plugins/types.py (AST
# literal guard, #round9-5), so the code for "no manifest and no warning
# at all" is derived from the contract Literal instead of being restated
# here. WARNING_REASON's first member is that code by the source order
# pinned in types.py.
_MISSING_MANIFEST: str = get_args(WARNING_REASON)[0]


@dataclass(frozen=True, init=False)
class PluginManager:
    """Frozen holder of discovery results with loaded/skipped views."""

    discovered_plugins: tuple[DiscoveredPlugin, ...] = ()

    def __init__(self, discovered: Sequence[DiscoveredPlugin] = ()) -> None:
        object.__setattr__(self, "discovered_plugins", tuple(discovered))

    def loaded(self) -> tuple[DiscoveredPlugin, ...]:
        """Plugins that survived discovery.

        Thin phase-0 semantics: a plugin counts as loaded when its
        manifest parsed (manifest is not None). T9 refines this to also
        exclude whole-plugin skip codes recorded in ``warnings``.
        """
        return tuple(plugin for plugin in self.discovered_plugins if plugin.manifest is not None)

    def skipped(self) -> tuple[tuple[str, str], ...]:
        """(distribution_name, reason) pairs for every non-loaded plugin.

        A plugin is skipped when its manifest is None or it carries
        warnings; the reason is its first warning code, falling back to
        the derived no-manifest code when there is no warning at all.
        """
        pairs: list[tuple[str, str]] = []
        for plugin in self.discovered_plugins:
            if plugin.manifest is not None and not plugin.warnings:
                continue
            reason = plugin.warnings[0] if plugin.warnings else _MISSING_MANIFEST
            pairs.append((plugin.distribution_name, reason))
        return tuple(pairs)

    def command_contributions(self) -> tuple[CommandContribution, ...]:
        """All command contributions from loaded plugins, in order."""
        return tuple(contribution for plugin in self.loaded() for contribution in plugin.commands)

    def format_providers(self) -> tuple[FormatProvider, ...]:
        """All format providers from loaded plugins, in order."""
        return tuple(provider for plugin in self.loaded() for provider in plugin.formats)
