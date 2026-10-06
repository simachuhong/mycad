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

    ``faces`` / ``edges`` accept any iterable at construction; they are
    normalised to tuples so the group is hashable-friendly and immutable.
    """

    name: str
    faces: tuple[FaceSelector, ...] = ()
    edges: tuple[EdgeSelector, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "faces", tuple(self.faces))
        object.__setattr__(self, "edges", tuple(self.edges))


__all__ = ["NamedGroup"]
