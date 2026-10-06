# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Archive migrations: the version-chain registry (v1 ships EMPTY).

Pure dict-to-dict transformations, no IO (persistence owns files). The
chain is walked hop by hop from the archive's discovered version towards
the supported version.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mycad.core.schema_v1 import ARCHIVE_VERSION

__all__ = ["Migration", "migrate", "register"]


@dataclass(frozen=True)
class Migration:
    """One hop in the version chain: ``from_version`` -> ``to_version``."""

    from_version: int
    to_version: int
    fn: Callable[[dict[str, Any]], dict[str, Any]]


#: Module-level registry; factory state is an EMPTY list (v1 has no hops).
_REGISTRY: list[Migration] = []


def register(migration: Migration) -> None:
    """Append ``migration`` to the chain registry (no dedup in v1)."""
    _REGISTRY.append(migration)


def migrate(data: dict[str, Any], *, supported_version: int = ARCHIVE_VERSION) -> dict[str, Any]:
    """Bring ``data`` up to ``supported_version``; identity when already there.

    No next hop (or a cyclic chain) -> ``ValueError`` carrying the
    discovered version and the registered migration count.
    """
    current = data.get("version")
    if current == supported_version:
        return data
    applied = 0
    while current != supported_version:
        hop = next((m for m in _REGISTRY if m.from_version == current), None)
        if hop is None or applied > len(_REGISTRY):
            raise ValueError(
                f"no migration path from archive version {current!r} to "
                f"{supported_version} ({len(_REGISTRY)} migrations registered, "
                f"{applied} applied)"
            )
        data = hop.fn(data)
        current = hop.to_version
        applied += 1
    return data
