# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Command registry (T3 command framework).

``CommandRegistry`` is constructor-injected (Document/Bus receive it; there is
deliberately no module-level default instance). ``schema_defs`` is the ONE
defs injection point: every ``validate_params`` call site passes
``defs=registry.schema_defs`` so a single shared ``$defs`` table backs the
whole process (the formal table itself is T7's
``src/mycad/builtin_commands/defs.py``).

Category is DERIVED from the command id's first segment — ``CommandSpec``
has no category field (``feature.extrude`` -> ``"feature"``,
``modify.fillet`` -> ``"modify"``, plugin ``demo.ping`` -> ``"demo"``).

Version policy: registering the same (id, version) twice raises
``CommandConflictError``; different versions coexist with the latest as the
default (API-level only — Phase 0 registers exactly version 1).
"""

from __future__ import annotations

from collections.abc import Mapping

from mycad.commands.spec import CommandSpec
from mycad.core.exceptions import CommandConflictError, UnknownCommandError

__all__ = ["CommandRegistry"]


def _category_of(command_id: str) -> str:
    return command_id.split(".", 1)[0]


class CommandRegistry:
    """Mutable, constructor-scoped registry of ``CommandSpec`` objects."""

    def __init__(self, schema_defs: Mapping[str, object] | None = None) -> None:
        self.schema_defs: Mapping[str, object] = (
            dict(schema_defs) if schema_defs is not None else {}
        )
        self._specs: dict[tuple[str, int], CommandSpec] = {}

    # -- registration -------------------------------------------------------

    def register(self, spec: CommandSpec) -> None:
        """Register ``spec``; same (id, version) again -> CommandConflictError."""
        key = (spec.id, spec.version)
        if key in self._specs:
            raise CommandConflictError(
                f"command {spec.id!r} version {spec.version} is already registered",
                command_id=spec.id,
            )
        self._specs[key] = spec

    # -- lookup -------------------------------------------------------------

    def get(self, command_id: str, version: int | None = None) -> CommandSpec:
        """Return the spec for ``command_id`` (latest version by default)."""
        versions = [v for (cid, v) in self._specs if cid == command_id]
        if not versions:
            raise UnknownCommandError(f"unknown command id {command_id!r}", identifier=command_id)
        chosen = max(versions) if version is None else version
        spec = self._specs.get((command_id, chosen))
        if spec is None:
            raise UnknownCommandError(
                f"unknown command id {command_id!r} version {version}", identifier=command_id
            )
        return spec

    def resolve_verb(self, verb: str) -> CommandSpec | None:
        """Resolve a CLI verb to a spec via each spec's ``cli.verb_aliases``.

        Returns ``None`` when no registered command claims ``verb``. When the
        latest versions of several distinct command ids claim the same verb
        the ambiguity is a registration conflict and raises
        ``CommandConflictError``.
        """
        by_id: dict[str, CommandSpec] = {}
        for spec in self._specs.values():
            if verb not in spec.cli.verb_aliases:
                continue
            current = by_id.get(spec.id)
            if current is None or spec.version > current.version:
                by_id[spec.id] = spec
        if not by_id:
            return None
        if len(by_id) > 1:
            claimants = ", ".join(sorted(by_id))
            raise CommandConflictError(
                f"verb {verb!r} is claimed by multiple commands: {claimants}"
            )
        return next(iter(by_id.values()))

    def _latest_specs(self) -> list[CommandSpec]:
        latest: dict[str, CommandSpec] = {}
        for spec in self._specs.values():
            current = latest.get(spec.id)
            if current is None or spec.version > current.version:
                latest[spec.id] = spec
        return [latest[command_id] for command_id in sorted(latest)]

    # -- browsing -----------------------------------------------------------

    def list_by_category(self) -> dict[str, list[CommandSpec]]:
        """Group latest specs by id first segment; groups and ids sorted."""
        groups: dict[str, list[CommandSpec]] = {}
        for spec in self._latest_specs():
            groups.setdefault(_category_of(spec.id), []).append(spec)
        return {
            category: sorted(specs, key=lambda s: s.id)
            for category, specs in sorted(groups.items())
        }

    def search(self, keyword: str) -> list[CommandSpec]:
        """Case-insensitive substring search over id + verb aliases + summary_en.

        ``label_zh`` is deliberately NOT searched: the Phase 0 CLI is English;
        the Chinese label is reserved for the Phase 1 UI search. No match
        returns ``[]`` (never ``None``, never raises).
        """
        needle = keyword.lower()
        hits = [
            spec
            for spec in self._latest_specs()
            if needle in spec.id.lower()
            or any(needle in alias.lower() for alias in spec.cli.verb_aliases)
            or needle in spec.summary_en.lower()
        ]
        return sorted(hits, key=lambda s: s.id)
