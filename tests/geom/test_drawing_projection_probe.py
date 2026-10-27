# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""T0 characterization of exact HLR, coordinates and bounded source evidence.

This is a probe, not the production drawing adapter. Hand-derived fixtures
catch mirror errors, missing occlusion and lost analytic curves.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import hypot
from typing import Literal, cast

import build123d
import pytest
from build123d import Box, Compound, Cylinder, Edge, Face, GeomType, Pos, Solid, Wire
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepLib import BRepLib
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.TopoDS import TopoDS, TopoDS_Shape

Point3 = tuple[float, float, float]
ProbeShape = Compound | Solid | Face | Edge | Wire


@dataclass(frozen=True)
class ProbeProjection:
    visible: tuple[Edge, ...] = ()
    hidden: tuple[Edge, ...] = ()
    tangent: tuple[Edge, ...] = ()
    outline: tuple[Edge, ...] = ()


def project(
    shape: ProbeShape,
    normal: Point3 = (0, 0, 1),
    up: Point3 = (0, 1, 0),
    source: ProbeShape | None = None,
) -> ProbeProjection:
    """Project the entire model while optionally selecting one source's results."""
    algo = HLRBRep_Algo()
    algo.Add(shape.wrapped)
    axes = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*normal))
    axes.SetYDirection(gp_Dir(*up))
    algo.Projector(HLRAlgo_Projector(axes))
    algo.Update()
    algo.Hide()
    output = HLRBRep_HLRToShape(algo)

    def extract(compound: TopoDS_Shape) -> tuple[Edge, ...]:
        if compound.IsNull():
            return ()
        edges = tuple(Compound(TopoDS.Compound_s(compound)).edges())
        for edge in edges:
            BRepLib.BuildCurves3d_s(edge.wrapped, 1e-7)
        return edges

    if source is None:
        return ProbeProjection(
            extract(output.VCompound()),
            extract(output.HCompound()),
            extract(output.Rg1LineVCompound()),
            extract(output.OutLineVCompound()),
        )
    # HLR reconstructs faces. Source overloads need the outlined faces, not
    # original faces: recover the explicit OCCT NewSOldS relation first.
    face_map = algo.DataStructure().FaceMap()
    history = algo.ShapeBounds(1).Shape().DataStructure()
    original_faces = source.faces()
    mapped: list[Face] = []
    for i in range(1, face_map.Extent() + 1):
        outlined = face_map.FindKey(i)
        original = history.NewSOldS(outlined)
        if any(face.wrapped.IsSame(original) for face in original_faces):
            mapped.append(Face(TopoDS.Face_s(outlined)))
    selected = Compound(mapped)
    return ProbeProjection(
        extract(output.VCompound(selected.wrapped)),
        extract(output.HCompound(selected.wrapped)),
        extract(output.Rg1LineVCompound(selected.wrapped)),
        extract(output.OutLineVCompound(selected.wrapped)),
    )


def flange(radius: float = 3) -> ProbeShape:
    part: Compound = Cylinder(40, 8)
    for x, y in ((25, 0), (0, 25), (-25, 0), (0, -25)):
        part = part - Pos(x, y, 0) * Cylinder(radius, 16)
    return part


def circles(edges: Sequence[Edge]) -> list[tuple[float, float, float]]:
    result: list[tuple[float, float, float]] = []
    for edge in edges:
        if edge.geom_type == GeomType.CIRCLE:
            center = edge.arc_center
            result.append((round(center.X, 6), round(center.Y, 6), round(edge.radius, 6)))
    return result


def resolve_cylinder(
    shape: ProbeShape, center_xy: tuple[float, float] | None
) -> tuple[Literal["resolved", "orphaned", "ambiguous"], tuple[Face, ...]]:
    """Bounded probe predicate: Z-axis cylindrical face, optional XY location."""
    matches: list[Face] = []
    for face in shape.faces():
        if face.geom_type != GeomType.CYLINDER:
            continue
        cylinder = BRepAdaptor_Surface(face.wrapped).Cylinder()
        axis = cylinder.Axis()
        if abs(axis.Direction().Z()) < 1 - 1e-8:
            continue
        point = axis.Location()
        if (
            center_xy is not None
            and hypot(point.X() - center_xy[0], point.Y() - center_xy[1]) > 1e-6
        ):
            continue
        matches.append(face)
    if len(matches) == 1:
        return "resolved", tuple(matches)
    return ("ambiguous" if matches else "orphaned"), ()


@pytest.mark.parametrize(
    "normal,up,want",
    [
        ((0, 0, 1), (0, 1, 0), (7, 4, 2)),
        ((0, 0, -1), (0, 1, 0), (-7, 4, 2)),
    ],
)
def test_asymmetric_offset_hole_is_not_mirrored(
    normal: Point3, up: Point3, want: tuple[float, float, float]
) -> None:
    shape = Box(40, 24, 8) - Pos(7, 4, 0) * Cylinder(2, 20)
    projection = project(shape, normal, up)
    assert want in circles(projection.visible)


def test_flange_keeps_pcd_and_hole_diameter() -> None:
    result = project(flange())
    holes = {(x, y, r) for x, y, r in circles(result.visible) if r == 3}
    assert holes == {(25, 0, 3), (0, 25, 3), (-25, 0, 3), (0, -25, 3)}
    assert all(hypot(x, y) == pytest.approx(25) for x, y, _ in holes)
    assert (0, 0, 40) in circles(result.visible)


def test_occluded_body_edge_is_hidden_in_joint_hlr() -> None:
    near = Pos(0, 0, 5) * Box(30, 30, 2)
    far = Pos(0, 0, -5) * Box(8, 6, 2)
    scene = Compound(children=[near, far])
    far_result = project(scene, source=far)
    assert not far_result.visible
    assert sum(edge.length for edge in far_result.hidden) > 20
    assert sum(edge.length for edge in project(far).visible) == pytest.approx(28)


def test_cylinder_silhouette_has_face_source() -> None:
    cylinder = Cylinder(5, 12)
    side = next(face for face in cylinder.faces() if face.geom_type == GeomType.CYLINDER)
    result = project(cylinder, (0, -1, 0), (0, 0, 1), source=side)
    # One outline coincides with the cylinder seam and appears in VCompound.
    # Assert geometric silhouette, not OCCT's internal bucket count.
    silhouette = [e for e in (*result.visible, *result.outline) if abs(e.length - 12) < 1e-7]
    assert sorted(e.start_point().X for e in silhouette) == pytest.approx([-5, 5])
    assert len(result.outline) >= 1


def test_oblique_circle_projection_remains_exact_ellipse() -> None:
    result = project(Cylinder(5, 12), (0, -1, 1), (0, 1, 1))
    assert any(edge.geom_type == GeomType.ELLIPSE for edge in result.visible)


def test_radius_change_resolves_without_runtime_ids() -> None:
    status, faces = resolve_cylinder(flange(4), (25, 0))
    assert status == "resolved"
    assert len(faces) == 1
    assert BRepAdaptor_Surface(faces[0].wrapped).Cylinder().Radius() == pytest.approx(4)


def test_deleted_and_ambiguous_sources_never_choose_nearest() -> None:
    assert resolve_cylinder(Box(80, 80, 8), (25, 0)) == ("orphaned", ())
    status, faces = resolve_cylinder(flange(), None)
    assert status == "ambiguous"
    assert not faces


def test_fillets_separate_tangent_edges_from_sharp_edges() -> None:
    from build123d import fillet

    box = Box(20, 30, 10)
    rounded = fillet(box.edges(), 2)
    result = project(rounded, (0, -1, 1), (0, 1, 1))
    assert result.tangent
    assert result.visible
    assert all(edge.length > 1e-7 for edge in (*result.visible, *result.tangent))


def test_rational_spline_projection_keeps_weights_and_exact_points() -> None:
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.Geom import Geom_BSplineCurve
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal

    poles = TColgp_Array1OfPnt(1, 4)
    weights = TColStd_Array1OfReal(1, 4)
    for i, (point, weight) in enumerate(
        zip(((0, 0, 2), (10, 20, 3), (20, -10, 4), (30, 5, 5)), (1, 2, 3, 1), strict=True),
        1,
    ):
        poles.SetValue(i, gp_Pnt(*point))
        weights.SetValue(i, weight)
    knots = TColStd_Array1OfReal(1, 2)
    mults = TColStd_Array1OfInteger(1, 2)
    for i, knot in enumerate((0, 1), 1):
        knots.SetValue(i, knot)
        mults.SetValue(i, 4)
    curve = Geom_BSplineCurve(poles, weights, knots, mults, 3)
    edge = Edge(BRepBuilderAPI_MakeEdge(curve).Edge())
    result = project(edge)
    assert len(result.visible) == 1
    projected = BRepAdaptor_Curve(result.visible[0].wrapped).BSpline()
    assert projected.Degree() == 3
    assert projected.IsRational()
    assert [projected.Weight(i) for i in range(1, 5)] == pytest.approx([1, 2, 3, 1])
    for parameter in (0, 0.25, 0.5, 0.75, 1):
        original = curve.Value(parameter)
        point = projected.Value(parameter)
        assert (point.X(), point.Y(), point.Z()) == pytest.approx(
            (original.X(), original.Y(), 0), abs=1e-7
        )


def benchmark_brep(path: str) -> dict[str, object]:
    """Isolated-process probe entry: plain path in, scalar JSON-compatible data out."""
    import os
    import sys
    from time import perf_counter

    load_brep = cast("Callable[[str], ProbeShape]", build123d.import_brep)
    shape = load_brep(path)
    durations: list[float] = []
    counts: list[int] = []
    for _ in range(5):
        start = perf_counter()
        for normal, up in (
            ((0, 0, 1), (0, 1, 0)),
            ((0, -1, 0), (0, 0, 1)),
            ((-1, 0, 0), (0, 0, 1)),
        ):
            result = project(shape, normal, up)
            counts.append(len(result.visible) + len(result.hidden) + len(result.outline))
        durations.append(perf_counter() - start)
    peak_rss_kib: int | None = None
    if sys.platform == "linux":
        import resource

        peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    ordered = sorted(durations)
    return {
        "pid": os.getpid(),
        "edges": len(shape.edges()),
        "faces": len(shape.faces()),
        "runs_s": durations,
        "p50_s": ordered[2],
        "p95_sample_s": ordered[-1],
        "peak_rss_kib": peak_rss_kib,
        "curve_counts": counts,
    }


def planar_width_reference(shape: ProbeShape) -> float | None:
    """Resolve two unique axis-normal planes; refuse a changed ambiguous feature."""
    negative: list[float] = []
    positive: list[float] = []
    for face in shape.faces():
        if face.geom_type != GeomType.PLANE:
            continue
        normal = face.normal_at()
        if normal.X < -1 + 1e-8:
            negative.append(face.center().X)
        elif normal.X > 1 - 1e-8:
            positive.append(face.center().X)
    if len(negative) != 1 or len(positive) != 1:
        return None
    return positive[0] - negative[0]


def test_length_edit_rebinds_unique_planar_sides() -> None:
    assert planar_width_reference(Box(40, 20, 8)) == pytest.approx(40)
    assert planar_width_reference(Box(65, 20, 8)) == pytest.approx(65)
    assert planar_width_reference(Cylinder(5, 8)) is None
    assert (
        planar_width_reference(Compound(children=[Box(10, 10, 8), Pos(20, 0, 0) * Box(10, 10, 8)]))
        is None
    )


@pytest.mark.parametrize(
    "normal,expected",
    [
        ((0, -1, 0), (-20, 30)),
        ((0, 1, 0), (-30, 20)),
        ((-1, 0, 0), (-15, 10)),
        ((1, 0, 0), (-10, 15)),
    ],
)
def test_asymmetric_step_front_back_left_right_extents(
    normal: Point3, expected: tuple[float, float]
) -> None:
    # Main block [-20,20]x[-10,10]x[-4,4], step extends to x=30,y=15,z=12.
    step = Box(40, 20, 8) + Pos(20, 5, 4) * Box(20, 20, 16)
    result = project(step, normal, (0, 0, 1))
    points = [point for edge in result.visible for point in (edge.start_point(), edge.end_point())]
    assert (min(point.X for point in points), max(point.X for point in points)) == pytest.approx(
        expected
    )
    assert (min(point.Y for point in points), max(point.Y for point in points)) == pytest.approx(
        (-4, 12)
    )
