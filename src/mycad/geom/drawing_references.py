# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Count competing source predicates before projected-edge deduplication."""

from bisect import bisect_left, bisect_right
from collections import defaultdict

from mycad.core.drawing_references import DrawingGeometryReference, same_source


def source_key(reference: DrawingGeometryReference) -> tuple[object, ...]:
    return (reference.kind, reference.owner_command, reference.parameters)


def source_multiplicities(
    references: tuple[DrawingGeometryReference, ...],
) -> dict[tuple[object, ...], int]:
    groups: dict[tuple[str, str | None, tuple[str, ...]], list[DrawingGeometryReference]] = (
        defaultdict(list)
    )
    for reference in references:
        groups[
            (reference.kind, reference.owner_command, tuple(k for k, _ in reference.parameters))
        ].append(reference)
    counts: dict[tuple[object, ...], int] = {}
    for rows in groups.values():
        columns = [
            sorted((row.parameters[column][1], index) for index, row in enumerate(rows))
            for column in range(len(rows[0].parameters))
        ]
        tolerances = [
            max(1e-6, 1e-9 * max(abs(value) for value, _ in column)) for column in columns
        ]
        for row in rows:
            ranges: list[tuple[int, int, int]] = []
            for column, ((_, value), entries, tolerance) in enumerate(
                zip(row.parameters, columns, tolerances, strict=True)
            ):
                lower = bisect_left(entries, (value - tolerance, -1))
                upper = bisect_right(entries, (value + tolerance, len(rows)))
                ranges.append((upper - lower, column, lower))
            candidates: set[int] | None = None
            for size, column, lower in sorted(ranges):
                matches = {index for _, index in columns[column][lower : lower + size]}
                candidates = matches if candidates is None else candidates & matches
                if len(candidates) <= 1:
                    break
            if candidates is None:
                candidates = set(range(len(rows)))
            counts[source_key(row)] = sum(same_source(row, rows[index]) for index in candidates)
    return counts
