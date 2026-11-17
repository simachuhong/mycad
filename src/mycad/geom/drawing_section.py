# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""BREP cutting for straight engineering sections; no UI or document writes."""

from dataclasses import dataclass, replace
from itertools import product
from math import ceil, floor, isfinite, sqrt
from typing import TYPE_CHECKING, cast

from build123d import Compound, Edge, Face, Keep, Part, Plane, Solid, section

from mycad.core.drawing_projection import (
    DrawingProjectionRequest,
    LineCurve,
    Point2,
    Point3,
    ProjectionResult,
)
from mycad.core.drawing_section import SectionPlane
from mycad.geom.drawing_projection import ProjectionSources, project_shape

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class SectionSlice:
    """The material behind the plane and its actual planar section faces."""

    remaining: Compound | Solid
    faces: tuple[Face, ...]


@dataclass(frozen=True, slots=True)
class SectionProjection:
    projection: ProjectionResult
    hatch: tuple[LineCurve, ...]


def cut_section(shape: Compound | Solid, definition: SectionPlane) -> SectionSlice:
    """Cut away the observer side; reject a plane that misses the material."""
    if len(shape.solids()) != 1:
        raise ValueError("section requires exactly one solid")
    basis = definition.basis
    plane = Plane(origin=definition.origin, x_dir=basis.right, z_dir=basis.normal)
    intersection = section(Part([shape]), section_by=plane)
    faces = tuple(intersection.faces())
    if not faces:
        raise ValueError("section plane does not cross the solid")
    front, cut = shape.split(plane, keep=Keep.BOTH)
    if front is None or cut is None:
        raise ValueError("section plane must pass through material")
    if isinstance(cut, list):
        remaining: Compound | Solid = Compound(cut)
    else:
        remaining = cut
    if not remaining.solids():
        raise ValueError("section did not produce solid material")
    return SectionSlice(remaining, faces)


def hatch_section(
    sliced: SectionSlice, definition: SectionPlane, spacing_model_mm: float
) -> tuple[LineCurve, ...]:
    """Intersect 45-degree lines with the actual section faces, including holes."""
    if not isfinite(spacing_model_mm) or spacing_model_mm <= 0:
        raise ValueError("section hatch spacing must be finite and positive")
    basis = definition.basis
    bounds: list[Point2] = []
    for face in sliced.faces:
        box = face.bounding_box()
        bounds.extend(
            basis.project((x, y, z))
            for x, y, z in product(
                (box.min.X, box.max.X),
                (box.min.Y, box.max.Y),
                (box.min.Z, box.max.Z),
            )
        )
    if not bounds:
        raise ValueError("section has no hatchable faces")
    offsets = [y - x for x, y in bounds]
    step = spacing_model_mm * sqrt(2)
    first, last = floor(min(offsets) / step), ceil(max(offsets) / step)
    if last - first > 5000:
        raise ValueError("section hatch exceeds the supported line count")
    extent = max(max(abs(x), abs(y)) for x, y in bounds) + max(offsets) - min(offsets) + step
    depth = sum(a * b for a, b in zip(definition.origin, basis.normal, strict=True))

    def world(x: float, y: float) -> Point3:
        return (
            x * basis.right[0] + y * basis.up[0] + depth * basis.normal[0],
            x * basis.right[1] + y * basis.up[1] + depth * basis.normal[1],
            x * basis.right[2] + y * basis.up[2] + depth * basis.normal[2],
        )

    lines: list[LineCurve] = []
    for index in range(first, last + 1):
        offset = index * step
        cutter = Edge.make_line(world(-extent, -extent + offset), world(extent, extent + offset))
        for face in sliced.faces:
            intersect = cast("Callable[[Edge], list[Edge] | None]", face.intersect)
            intersections = intersect(cutter)
            if intersections is None:
                continue
            for part in intersections:
                for edge in part.edges():
                    a, b = edge.position_at(0), edge.position_at(1)
                    start = basis.project((a.X, a.Y, a.Z))
                    end = basis.project((b.X, b.Y, b.Z))
                    if abs(end[0] - start[0]) + abs(end[1] - start[1]) > 1e-9:
                        lines.append(LineCurve(start, end))
    return tuple(lines)


def project_section(
    shape: Compound | Solid,
    definition: SectionPlane,
    request: DrawingProjectionRequest,
    spacing_model_mm: float,
) -> SectionProjection:
    """Project a cut solid and return its section hatch as separate linework."""
    if request.source != "current_part" or request.basis != definition.basis:
        raise ValueError("section projection must match the part and section basis")
    sliced = cut_section(shape, definition)
    # Only faces explicitly matched to the original source by HLR history
    # receive references; the new cut faces cannot acquire guessed identities.
    projection = project_shape(sliced.remaining, request, ProjectionSources(shape))
    hatch = hatch_section(sliced, definition, spacing_model_mm)
    return SectionProjection(replace(projection, hatch=hatch), hatch)
