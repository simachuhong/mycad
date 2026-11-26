# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Format dimension labels consistently across drawing and part views."""

from mycad.core.sketch_constraints import SketchConstraint


def dimension_text(constraint: SketchConstraint) -> str:
    """Substitute the current value into an optional display-only override."""
    if constraint.value is None:
        return ""
    number = f"{constraint.value:.{constraint.precision}f}"
    return dimension_text_with_number(constraint, number)


def dimension_text_with_number(constraint: SketchConstraint, number: str) -> str:
    """Apply the dimension's prefix, suffix and override to an already formatted value."""
    if constraint.text_override is not None:
        return constraint.text_override.replace("<>", number)
    suffix = "°" if constraint.kind == "angle" else " mm"
    prefix = {"radius": "R", "diameter": "⌀", "arc_length": "⌒"}.get(constraint.kind, "")
    return f"{prefix}{number}{suffix}"
