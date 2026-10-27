# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact OCCT HLR adapter; only frozen core curves cross this boundary."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import replace
from typing import Literal

from build123d import Compound, Edge, Face, GeomType, Solid, Wire
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepLib import BRepLib
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.TopoDS import TopoDS, TopoDS_Shape

from mycad.core.drawing_projection import (
    ArcCurve,
    CurveGeometry,
    DrawingProjectionRequest,
    EllipseCurve,
    LineCurve,
    ProjectedCurve,
    ProjectionResult,
    SplineCurve,
)
from mycad.core.drawing_references import DrawingGeometryReference
from mycad.geom.drawing_references import source_key, source_multiplicities

Shape = Compound | Solid | Face | Edge | Wire
Visibility = Literal["visible", "hidden", "tangent"]
CurveKey = tuple[tuple[float, float], ...] | SplineCurve


def exact_curve(edge: Edge) -> CurveGeometry:
    """Preserve OCCT analytic curves and trimmed rational spline data."""
    adaptor = BRepAdaptor_Curve(edge.wrapped)
    first, last = adaptor.FirstParameter(), adaptor.LastParameter()
    if edge.geom_type == GeomType.LINE:
        a, b = adaptor.Value(first), adaptor.Value(last)
        return LineCurve((a.X(), a.Y()), (b.X(), b.Y()))
    if edge.geom_type in (GeomType.CIRCLE, GeomType.ELLIPSE):
        if edge.geom_type == GeomType.CIRCLE:
            circle = adaptor.Circle()
            center, axes = circle.Location(), circle.Position()
            major = minor = circle.Radius()
        else:
            ellipse = adaptor.Ellipse()
            center, axes = ellipse.Location(), ellipse.Position()
            major, minor = ellipse.MajorRadius(), ellipse.MinorRadius()
        xaxis = axes.XDirection()
        rotation = math.degrees(math.atan2(xaxis.Y(), xaxis.X()))
        sign = 1 if axes.Direction().Z() > 0 else -1
        sweep = sign * min(360.0, math.degrees(last - first))
        if edge.geom_type == GeomType.CIRCLE:
            return ArcCurve(
                (center.X(), center.Y()), major, rotation + sign * math.degrees(first), sweep
            )
        return EllipseCurve(
            (center.X(), center.Y()), major, minor, rotation, sign * math.degrees(first), sweep
        )
    if edge.geom_type == GeomType.BSPLINE:
        curve = adaptor.BSpline()
        curve.Segment(first, last, 1e-9)
        poles = tuple(
            (point.X(), point.Y())
            for point in (curve.Pole(i) for i in range(1, curve.NbPoles() + 1))
        )
        a, b = adaptor.Value(first), adaptor.Value(last)
        dx, dy = b.X() - a.X(), b.Y() - a.Y()
        length2 = dx * dx + dy * dy
        # Edge-on conics may arrive as splines. Positive-weight poles on the
        # endpoint segment prove the exact geometric image is that segment.
        if length2 > 1e-14 and all(
            abs((x - a.X()) * dy - (y - a.Y()) * dx) <= 1e-9 * math.sqrt(length2)
            and -1e-9 <= ((x - a.X()) * dx + (y - a.Y()) * dy) / length2 <= 1 + 1e-9
            for x, y in poles
        ):
            return LineCurve((a.X(), a.Y()), (b.X(), b.Y()))
        return SplineCurve(
            poles,
            curve.Degree(),
            tuple(curve.Knot(i) for i in range(1, curve.NbKnots() + 1)),
            tuple(curve.Multiplicity(i) for i in range(1, curve.NbKnots() + 1)),
            tuple(curve.Weight(i) for i in range(1, curve.NbPoles() + 1)),
            curve.IsPeriodic(),
        )
    raise ValueError(f"Unsupported exact projected curve: {edge.geom_type.name}")


def face_reference(face: Face) -> DrawingGeometryReference | None:
    if face.geom_type == GeomType.CYLINDER:
        axis = BRepAdaptor_Surface(face.wrapped).Cylinder().Axis()
        n, p = axis.Direction(), axis.Location()
        direction = (n.X(), n.Y(), n.Z())
        sign = next((1 if v > 0 else -1 for v in direction if abs(v) > 1e-9), 1)
        direction = tuple(sign * v for v in direction)
        # Axis location is canonical: nearest point on axis to world origin.
        dot = p.X() * n.X() + p.Y() * n.Y() + p.Z() * n.Z()
        point = (p.X() - dot * n.X(), p.Y() - dot * n.Y(), p.Z() - dot * n.Z())
        # The oriented material side separates an outer cylinder from a
        # coaxial bore without binding to the editable radius. Sampling uses
        # surface UV geometry, not a nearest candidate or face index.
        sample = face.position_at(0.37, 0.5)
        normal = face.normal_at(0.37, 0.5)
        outward = sum(
            (value - origin) * component
            for value, origin, component in zip(
                (sample.X, sample.Y, sample.Z), point, (normal.X, normal.Y, normal.Z), strict=True
            )
        )
        values = (*point, *direction, 1.0 if outward > 0 else -1.0)
        return DrawingGeometryReference(
            "cylindrical_face",
            tuple(zip(("x", "y", "z", "nx", "ny", "nz", "material_side"), values, strict=True)),
        )
    if face.geom_type == GeomType.PLANE:
        normal = face.normal_at()
        center = face.center()
        # Direction and tangential location persist when a planar side moves.
        n = (normal.X, normal.Y, normal.Z)
        dot = center.X * n[0] + center.Y * n[1] + center.Z * n[2]
        values = (*n, center.X - dot * n[0], center.Y - dot * n[1], center.Z - dot * n[2])
        return DrawingGeometryReference(
            "planar_face", tuple(zip(("nx", "ny", "nz", "tx", "ty", "tz"), values, strict=True))
        )
    return None


def _edges(shape: TopoDS_Shape) -> tuple[Edge, ...]:
    if shape.IsNull():
        return ()
    result = tuple(Compound(TopoDS.Compound_s(shape)).edges())
    for edge in result:
        BRepLib.BuildCurves3d_s(edge.wrapped, 1e-7)
    return result


def _key(edge: Edge) -> CurveKey:
    # Geometry-only identity within one projection, not a persistent reference.
    # Finite samples cannot identify arbitrary splines: keep their exact data.
    if edge.geom_type == GeomType.BSPLINE:
        curve = exact_curve(edge)
        if isinstance(curve, LineCurve):
            return tuple(
                sorted(
                    (
                        (round(curve.start[0], 7), round(curve.start[1], 7)),
                        (round(curve.end[0], 7), round(curve.end[1], 7)),
                    )
                )
            )
        assert isinstance(curve, SplineCurve)
        return curve
    adaptor = BRepAdaptor_Curve(edge.wrapped)
    first, last = adaptor.FirstParameter(), adaptor.LastParameter()
    if edge.geom_type == GeomType.LINE:
        a, b = adaptor.Value(first), adaptor.Value(last)
        return tuple(
            sorted(((round(a.X(), 7), round(a.Y(), 7)), (round(b.X(), 7), round(b.Y(), 7))))
        )
    points = tuple(
        (round(point.X(), 7), round(point.Y(), 7))
        for point in (
            adaptor.Value(first + (last - first) * fraction) for fraction in (0, 0.25, 0.5, 0.75, 1)
        )
    )
    return min(points, tuple(reversed(points)))


class ProjectionSources:
    """Reusable semantic evidence for one immutable shape, resolved lazily."""

    def __init__(self, shape: Shape) -> None:
        self.faces = tuple(shape.faces())
        self._groups: dict[GeomType, tuple[tuple[Face, DrawingGeometryReference], ...]] = {}
        self._counts: dict[GeomType, dict[tuple[object, ...], int]] = {}

    def groups(
        self,
    ) -> Iterator[
        tuple[tuple[tuple[Face, DrawingGeometryReference], ...], dict[tuple[object, ...], int]]
    ]:
        for kind in (GeomType.CYLINDER, GeomType.PLANE):
            if kind not in self._groups:
                pairs: list[tuple[Face, DrawingGeometryReference]] = []
                for face in self.faces:
                    if face.geom_type == kind:
                        reference = face_reference(face)
                        if reference is not None:
                            pairs.append((face, reference))
                self._groups[kind] = tuple(pairs)
                self._counts[kind] = source_multiplicities(tuple(ref for _, ref in pairs))
            yield self._groups[kind], self._counts[kind]


def project_shape(
    shape: Shape, request: DrawingProjectionRequest, sources: ProjectionSources | None = None
) -> ProjectionResult:
    if not shape.edges():
        raise ValueError("Cannot project empty source geometry")
    algo = HLRBRep_Algo()
    algo.Add(shape.wrapped)
    axes = gp_Ax2(gp_Pnt(), gp_Dir(*request.basis.normal))
    axes.SetYDirection(gp_Dir(*request.basis.up))
    algo.Projector(HLRAlgo_Projector(axes))
    algo.Update()
    algo.Hide()
    output = HLRBRep_HLRToShape(algo)
    geometry: dict[CurveKey, ProjectedCurve] = {}
    diagnostics: list[str] = []
    groups: tuple[tuple[TopoDS_Shape, Visibility, bool], ...] = (
        (output.VCompound(), "visible", False),
        (output.OutLineVCompound(), "visible", True),
        (output.HCompound(), "hidden", False),
        (output.OutLineHCompound(), "hidden", True),
        (output.Rg1LineVCompound(), "tangent", False),
    )
    for compound, visibility, silhouette in groups:
        for edge in _edges(compound):
            if edge.length < 1e-7:
                continue
            key = _key(edge)
            if key in geometry:
                if silhouette:
                    geometry[key] = replace(geometry[key], silhouette=True)
                continue
            try:
                curve = exact_curve(edge)
            except ValueError as error:
                diagnostics.append(str(error))
                continue
            geometry[key] = ProjectedCurve(
                f"curve-{len(geometry)}", curve, visibility, silhouette=silhouette
            )
    # Recover original faces through HLR's explicit history (not topology index).
    face_map = algo.DataStructure().FaceMap()
    history = algo.ShapeBounds(1).Shape().DataStructure()
    # Index the explicit HLR history once. Hash is only a lookup accelerator;
    # IsSame still establishes the original-face correspondence.
    outlined_by_original: dict[int, list[tuple[TopoDS_Shape, Face]]] = {}
    for i in range(1, face_map.Extent() + 1):
        outlined = face_map.FindKey(i)
        original = history.NewSOldS(outlined)
        outlined_by_original.setdefault(hash(original), []).append(
            (original, Face(TopoDS.Face_s(outlined)))
        )

    sources = sources or ProjectionSources(shape)
    unassigned = set(geometry)
    for pairs, counts in sources.groups():

        def priority(pair: tuple[Face, DrawingGeometryReference]) -> float:
            parameters = dict(pair[1].parameters)
            return abs(
                sum(
                    parameters[name] * value
                    for name, value in zip(("nx", "ny", "nz"), request.basis.normal, strict=True)
                )
            )

        # Cylinders first; only resolve planar evidence if some curves remain.
        # Edge-on planar sources identify moving sides instead of broad faces.
        for face, reference in sorted(pairs, key=priority):
            if not unassigned:
                break
            original = face.wrapped
            mapped = [
                outlined
                for source, outlined in outlined_by_original.get(hash(original), ())
                if source.IsSame(original)
            ]
            if not mapped:
                continue
            selected = Compound(mapped).wrapped
            for compound in (
                output.VCompound(selected),
                output.HCompound(selected),
                output.OutLineVCompound(selected),
                output.OutLineHCompound(selected),
            ):
                for edge in _edges(compound):
                    if edge.length < 1e-7:
                        continue
                    key = _key(edge)
                    if key in geometry and geometry[key].source is None:
                        geometry[key] = replace(
                            geometry[key],
                            source=reference,
                            source_count=counts[source_key(reference)],
                        )
                        unassigned.discard(key)
        if not unassigned:
            break
    return ProjectionResult(
        request.view_id,
        request.source_fingerprint,
        request.generation,
        tuple(geometry.values()),
        tuple(dict.fromkeys(diagnostics)),
    )
