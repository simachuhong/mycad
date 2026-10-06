# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Prioritized format-provider registry (T8a), implementing T6 FormatResolver.

Resolution rule: among providers claiming an extension, the smallest
``priority`` wins. Registering two providers with the same priority and
overlapping extensions raises ``ProviderConflictError``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import cast

from mycad.core.exceptions import ProviderConflictError, UnknownFormatError
from mycad.core.ports import FormatPort
from mycad.formats.base import FormatProvider


class FormatProviderRegistry:
    """Registry of ``FormatProvider``s resolved by file extension."""

    def __init__(self, providers: Iterable[FormatProvider] = ()) -> None:
        self._providers: list[FormatProvider] = []
        for provider in providers:
            self.register(provider)

    def register(self, provider: FormatProvider) -> None:
        """Append ``provider``; same-priority extension overlap is rejected."""

        for registered in self._providers:
            overlap = sorted(set(registered.extensions) & set(provider.extensions))
            if overlap and registered.priority == provider.priority:
                msg = (
                    f"extension {overlap[0]} is claimed by two providers with "
                    f"priority {provider.priority}: ({registered.name}, "
                    f"{registered.vendor}) and ({provider.name}, {provider.vendor})"
                )
                raise ProviderConflictError(
                    message=msg,
                    extension=overlap[0],
                    provider1=(registered.name, registered.vendor),
                    provider2=(provider.name, provider.vendor),
                )
        self._providers.append(provider)

    def get_by_extension(self, ext: str) -> FormatProvider:
        """Return the lowest-priority provider handling ``ext``, else raise."""

        norm = ext.lower()
        if not norm.startswith("."):
            norm = f".{norm}"
        candidates = [p for p in self._providers if norm in p.extensions]
        if not candidates:
            msg = f"no registered provider handles {norm!r}"
            raise UnknownFormatError(message=msg)
        return min(candidates, key=lambda p: p.priority)

    def list_providers(self) -> tuple[FormatProvider, ...]:
        """Registered providers in registration order."""

        return tuple(self._providers)

    def resolve(self, path: Path) -> FormatPort:
        """Return the provider responsible for ``path``'s extension."""

        # FormatProvider is frozen (read-only members) while FormatPort declares
        # settable ones; the port is only ever read, so bridge via a cast.
        return cast(FormatPort, self.get_by_extension(path.suffix.lower()))
