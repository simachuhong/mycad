# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Stable dependency ordering, independent of document or workspace count."""

from collections.abc import Mapping

from mycad.core.exceptions import ValidationError


def save_order(nodes: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    ordered: list[str] = []
    done: set[str] = set()
    visiting: set[str] = set()

    def visit(identity: str) -> None:
        if identity in done:
            return
        if identity in visiting:
            raise ValidationError("cyclic document dependency")
        visiting.add(identity)
        for dependency in nodes.get(identity, ()):
            if dependency in nodes:
                visit(dependency)
        visiting.remove(identity)
        done.add(identity)
        ordered.append(identity)

    for identity in nodes:
        visit(identity)
    return tuple(ordered)
