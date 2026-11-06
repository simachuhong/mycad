# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Stable document-kind names and the released independent-drawing commands."""

from __future__ import annotations

from typing import Literal

DocumentType = Literal["part", "drawing2d"]
DocumentKind = Literal["sketch", "drawing", "part"]


def native_suffix(kind: DocumentKind) -> str:
    return ".my3d" if kind == "part" else ".my2d"


# Extensions name native JSON archives; the payload remains the source of type/version.
# .masm is reserved for assembly documents, which are not supported yet.
NATIVE_ARCHIVE_SUFFIXES = (".my2d", ".my3d", ".mc.json")

# Commands permitted to change a standalone drawing. Keep this explicit so a
# plugin command cannot smuggle solid-modeling behavior into a drawing file.
DRAWING2D_COMMAND_IDS = frozenset(
    {
        "drawing.layers.set",
        "sketch.create",
        "sketch.revise",
        "drawing.sketch.revise",
        "sketch.constraint.add",
        "sketch.constraint.update",
        "drawing.sheet.create",
        "drawing.sheet.update",
        "drawing.sheet.delete",
        "drawing.view.create",
        "drawing.view.update",
        "drawing.view.delete",
        "drawing.annotation.create",
        "drawing.annotation.update",
        "drawing.annotation.delete",
        "drawing.note.create",
        "drawing.note.update",
        "drawing.note.delete",
        "reference.attach",
        "reference.update",
        "reference.detach",
    }
)

__all__ = [
    "DRAWING2D_COMMAND_IDS",
    "NATIVE_ARCHIVE_SUFFIXES",
    "DocumentKind",
    "DocumentType",
    "native_suffix",
]
