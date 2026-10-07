# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Plugin-system package (T7b/T9a): public contract re-exports.

Exactly seven public names: the contract shapes live in
``mycad.plugins.types``, the thin manager in ``mycad.plugins.manager``
and the entry-point discoverer in ``mycad.plugins.discovery``.
"""

from mycad.plugins.discovery import EntryPointDiscoverer
from mycad.plugins.manager import PluginManager
from mycad.plugins.types import (
    CURRENT_API_VERSION,
    CommandContribution,
    DiscoveredPlugin,
    PluginDiscoverer,
    PluginManifest,
)

__all__ = [
    "CURRENT_API_VERSION",
    "CommandContribution",
    "DiscoveredPlugin",
    "EntryPointDiscoverer",
    "PluginDiscoverer",
    "PluginManager",
    "PluginManifest",
]
