# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Plugin loader (T9b): register discovered contributions, isolate conflicts.

``register_plugins`` feeds a discovery result into the two registries,
treating every conflict as a per-entry skip: a colliding command spec or
format provider drops only that entry — never the plugin's remaining
entries — and is reported through the plugin's ``warnings`` tuple.

Warning codes: ``warnings`` carries ONLY the six contract codes derived
from ``WARNING_REASON``. The provider name/vendor detail the plan asks
for ("warning includes both providers' name/vendor") is delivered
through the ``ProviderConflictError`` fields (``extension`` plus the
``provider1``/``provider2`` (name, vendor) tuples) and asserted in the
direct-registration unit test, not embedded in a free-form warning
string; the T9b evidence notes record this explained deviation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import get_args

from mycad.commands.registry import CommandRegistry
from mycad.core.exceptions import CommandConflictError, ProviderConflictError
from mycad.formats.registry import FormatProviderRegistry
from mycad.plugins.types import (
    WARNING_REASON,
    CommandContribution,
    DiscoveredPlugin,
    FormatProvider,
)

__all__ = ["register_plugins"]

# Derived from the contract Literal (source order, #round9-5): the two
# per-entry conflict codes this loader can record. No other code is ever
# appended to a DiscoveredPlugin's warnings by this module.
_COMMAND_CONFLICT: str = get_args(WARNING_REASON)[3]
_PROVIDER_CONFLICT: str = get_args(WARNING_REASON)[4]


def register_plugins(
    registry: CommandRegistry,
    formats_registry: FormatProviderRegistry,
    discovered: Sequence[DiscoveredPlugin],
) -> tuple[DiscoveredPlugin, ...]:
    """Register every discovered contribution, isolating conflicts per entry.

    Plugins are processed in input order (discovery already sorted them).
    Command specs are registered one by one — a ``CommandConflictError``
    skips only that entry, never the plugin's remaining commands. Format
    providers likewise — a ``ProviderConflictError`` skips only that
    provider entry. Each result element is a NEW ``DiscoveredPlugin``
    (the inputs are never mutated) whose ``commands``/``formats`` carry
    only the surviving entries and whose ``warnings`` is the original
    tuple plus the newly recorded codes, deduplicated in first-seen
    order. The result feeds the ``PluginManager`` constructor.
    """
    loaded: list[DiscoveredPlugin] = []
    for plugin in discovered:
        new_warnings: list[str] = []
        alive_commands: list[CommandContribution] = []
        for contribution in plugin.commands:
            try:
                registry.register(contribution.spec)
            except CommandConflictError:
                new_warnings.append(_COMMAND_CONFLICT)
                continue
            alive_commands.append(contribution)
        alive_formats: list[FormatProvider] = []
        for provider in plugin.formats:
            try:
                formats_registry.register(provider)
            except ProviderConflictError:
                new_warnings.append(_PROVIDER_CONFLICT)
                continue
            alive_formats.append(provider)
        merged = tuple(dict.fromkeys((*plugin.warnings, *new_warnings)))
        loaded.append(
            replace(
                plugin,
                commands=tuple(alive_commands),
                formats=tuple(alive_formats),
                warnings=merged,
            )
        )
    return tuple(loaded)
