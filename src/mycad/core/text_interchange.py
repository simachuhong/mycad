# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Reconcile imported text resources without changing existing document styles."""

from dataclasses import replace
from uuid import uuid4

from mycad.core.drawing_text import DrawingText, TextStyleTable


def reconcile_text_styles(
    texts: tuple[DrawingText, ...], source: TextStyleTable, target: TextStyleTable
) -> tuple[TextStyleTable, tuple[DrawingText, ...]]:
    """Reuse equivalent styles or allocate collision-free IDs and display names."""
    table, remap = reconcile_text_style_ids(
        tuple(dict.fromkeys(text.style_id for text in texts)), source, target
    )
    return table, tuple(replace(text, style_id=remap[text.style_id]) for text in texts)


def reconcile_text_style_ids(
    style_ids: tuple[str, ...], source: TextStyleTable, target: TextStyleTable
) -> tuple[TextStyleTable, dict[str, str]]:
    """Merge referenced text styles and return their destination identities."""
    styles = list(target.styles)
    identities = {style.style_id for style in styles}
    names = {style.name.casefold() for style in styles}
    remap: dict[str, str] = {}
    for identity in dict.fromkeys(style_ids):
        incoming = source.get(identity)
        equivalent = next(
            (
                style
                for style in styles
                if replace(style, style_id=incoming.style_id, name=incoming.name) == incoming
            ),
            None,
        )
        if equivalent is not None:
            remap[identity] = equivalent.style_id
            continue
        new_identity = uuid4().hex if identity in identities else identity
        name, suffix = incoming.name, 1
        while name.casefold() in names:
            suffix += 1
            name = f"{incoming.name[:480]} ({suffix})"
        styles.append(replace(incoming, style_id=new_identity, name=name))
        identities.add(new_identity)
        names.add(name.casefold())
        remap[identity] = new_identity
    return TextStyleTable(tuple(styles), target.current_id), remap
