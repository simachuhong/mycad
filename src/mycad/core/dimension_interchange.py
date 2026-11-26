# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Reconcile clipboard dimension styles and their font identities."""

from dataclasses import replace

from mycad.core.dimension_styles import DimensionStyleTable
from mycad.core.drawing_text import TextStyleTable
from mycad.core.sketch import Sketch
from mycad.core.text_interchange import reconcile_text_style_ids


def reconcile_clipboard_fonts(
    styles: DimensionStyleTable, source: TextStyleTable, target: TextStyleTable
) -> tuple[DimensionStyleTable, TextStyleTable]:
    """Preserve font style semantics when clipboard identities collide."""
    font_ids = tuple(
        style.text_style_id for style in styles.styles if style.text_style_id is not None
    )
    merged, mapping = reconcile_text_style_ids(font_ids, source, target)
    return replace(
        styles,
        styles=tuple(
            replace(style, text_style_id=mapping[style.text_style_id])
            if style.text_style_id is not None
            else style
            for style in styles.styles
        ),
    ), merged


def reconcile_clipboard_styles(
    sketch: Sketch, source: DimensionStyleTable, destination: DimensionStyleTable
) -> tuple[DimensionStyleTable, Sketch]:
    """Reuse identical styles and give conflicting source styles distinct names."""
    combined = list(destination.styles)
    names: dict[str, str] = {}
    for original in source.styles:
        equivalent = next(
            (style for style in combined if replace(style, name=original.name) == original), None
        )
        if equivalent is not None:
            names[original.name.casefold()] = equivalent.name
            continue
        existing = {style.name.casefold() for style in combined}
        name = original.name
        index = 1
        while name.casefold() in existing:
            suffix = f" ({index})"
            name = original.name[: 80 - len(suffix)] + suffix
            index += 1
        combined.append(replace(original, name=name))
        names[original.name.casefold()] = name
    styles = DimensionStyleTable(tuple(combined), destination.current_name)
    constraints = tuple(
        replace(c, style_name=names[c.style_name.casefold()]) if c.style_name is not None else c
        for c in sketch.constraints
    )
    return styles, replace(sketch, constraints=constraints)
