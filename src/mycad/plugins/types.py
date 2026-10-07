# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Plugin-system public contract types (T7b).

Single definition site of the cross-wave plugin contract (#round9-4):
T9 imports and consumes these symbols from ``mycad.plugins.types`` and
must not add, remove or alter any field defined here. The discovery
algorithm (manifest location, api gating, conflict handling) is a T9
implementation detail — this module carries data shapes only.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, get_args, runtime_checkable

from mycad.commands.spec import CommandSpec
from mycad.core.handlers import CommandHandler
from mycad.formats.base import FormatProvider

#: Plugin API version this build speaks; ``CURRENT_API_MAJOR`` drives the
#: major-version compatibility gate (plan #round8-3: any 1.x loads).
CURRENT_API_VERSION: str = "1.0"
CURRENT_API_MAJOR: int = 1

#: Exhaustive skip-reason vocabulary (#round9-5): every skip event's
#: reason is one of these six codes; T9 warning emission and the T10
#: ``plugins`` subcommand output share this Literal.
WARNING_REASON = Literal[
    "missing-manifest",
    "manifest-error",
    "incompatible-api",
    "command-conflict",
    "provider-conflict",
    "load-error",
]

WARNING_REASONS: frozenset[str] = frozenset(get_args(WARNING_REASON))


@dataclass(frozen=True)
class CommandContribution:
    """One command a plugin offers: its spec plus an optional handler factory.

    ``handler_factory`` is a zero-argument callable returning a fresh
    ``CommandHandler`` bound to ``spec.id``; ``None`` when the plugin
    contributes a spec without an executable handler.
    """

    spec: CommandSpec
    handler_factory: Callable[[], CommandHandler] | None


@runtime_checkable
class PluginDiscoverer(Protocol):
    """Discovery contract: yields one DiscoveredPlugin per distribution.

    T9 provides the sole implementation (``EntryPointDiscoverer``,
    scanning the two importlib.metadata entry groups); phase 0 wires an
    empty discovery list.
    """

    def discover(self) -> Sequence[DiscoveredPlugin]:
        """Return every plugin visible to this discoverer, in stable order."""
        ...


@dataclass(frozen=True)
class DiscoveredPlugin:
    """Everything discovery learned about one installed distribution.

    ``manifest`` is None when the manifest attribute is missing or
    damaged; in that case ``commands`` and ``formats`` are empty tuples
    and ``warnings`` carries the reason codes. ``entrypoint`` holds the
    distribution's entry-point reference strings, deduplicated and
    sorted, in ``<group>:<module>:<attr>`` form.
    """

    distribution_name: str
    entrypoint: tuple[str, ...]
    manifest: PluginManifest | None
    commands: tuple[CommandContribution, ...] = ()
    formats: tuple[FormatProvider, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginManifest:
    """Static plugin metadata; ``api_version`` drives the load gate.

    Phase 0 stores ``permissions`` for display only (nothing is
    enforced); ``homepage`` is optional display data.
    """

    id: str
    version: str
    api_version: str
    permissions: tuple[str, ...] = ()
    homepage: str = ""
