# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Plugin-system package (T7b): public contract re-exports.

Exactly six public names (plan T7): the contract shapes live in
``mycad.plugins.types`` and the thin manager in ``mycad.plugins.manager``.
"""

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
    "PluginDiscoverer",
    "PluginManager",
    "PluginManifest",
]
