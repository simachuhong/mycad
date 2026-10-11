# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Named groups of face/edge selectors (#10).

A :class:`NamedGroup` bundles selector descriptors under a name so later
commands can target a stable set of topology without numeric indices.
``name`` non-emptiness is validated by the Document API (T6b), not here.
"""

from __future__ import annotations

from dataclasses import dataclass

from mycad.core.selectors import EdgeSelector, FaceSelector


@dataclass(frozen=True)
class NamedGroup:
    """A named bundle of face and edge selectors.

    ``faces`` / ``edges`` are tuples so the group stays immutable and
    hashable-friendly; the JSON loader materialises them as such.
    """

    name: str
    faces: tuple[FaceSelector, ...] = ()
    edges: tuple[EdgeSelector, ...] = ()


__all__ = ["NamedGroup"]
