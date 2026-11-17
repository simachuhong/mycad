# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""OCCT-backed exact detail clipping for projected ellipses and splines."""

from math import cos, degrees, dist, radians, sin

from OCP.Geom2d import Geom2d_BSplineCurve, Geom2d_Circle, Geom2d_Ellipse
from OCP.Geom2dAPI import Geom2dAPI_InterCurveCurve
from OCP.gp import gp_Ax2d, gp_Dir2d, gp_Pnt2d
from OCP.TColgp import TColgp_Array1OfPnt2d
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal

from mycad.core.drawing_detail import DetailRegion, clip_detail
from mycad.core.drawing_projection import CurveGeometry, EllipseCurve, SplineCurve


def clip_detail_exact(curve: CurveGeometry, region: DetailRegion) -> tuple[CurveGeometry, ...]:
    """Keep analytic ellipses; ambiguous boundary contacts fail closed."""
    try:
        return clip_detail(curve, region)
    except ValueError:
        if isinstance(curve, SplineCurve):
            return _clip_spline(curve, region)
        if not isinstance(curve, EllipseCurve):
            raise
    angle = radians(curve.rotation_deg)
    axis = gp_Ax2d(gp_Pnt2d(*curve.center), gp_Dir2d(cos(angle), sin(angle)))
    ellipse = Geom2d_Ellipse(axis, curve.major_radius, curve.minor_radius)
    circle = Geom2d_Circle(gp_Ax2d(gp_Pnt2d(*region.center), gp_Dir2d(1, 0)), region.radius)
    intersection = Geom2dAPI_InterCurveCurve(ellipse, circle, 1e-9)
    algorithm = intersection.Intersector()
    if not algorithm.IsDone() or intersection.NbSegments():
        raise ValueError("详图边界与椭圆相切或重合，暂不能安全裁剪")
    cuts = [0.0, 1.0]
    for index in range(1, intersection.NbPoints() + 1):
        boundary = degrees(algorithm.Point(index).ParamOnFirst())
        travel = (
            (boundary - curve.start_deg) % 360
            if curve.sweep_deg > 0
            else (curve.start_deg - boundary) % 360
        )
        parameter = travel / abs(curve.sweep_deg)
        if 1e-12 < parameter < 1 - 1e-12:
            cuts.append(parameter)
    cuts = sorted(set(cuts))
    pieces: list[CurveGeometry] = []
    for start, end in zip(cuts, cuts[1:], strict=False):
        point = ellipse.Value(radians(curve.start_deg + (start + end) * curve.sweep_deg / 2))
        gap = dist((point.X(), point.Y()), region.center)
        if abs(gap - region.radius) <= 1e-9 * max(1, region.radius):
            raise ValueError("详图边界与椭圆的关系不明确，请调整详图范围")
        if gap < region.radius and end - start > 1e-12:
            pieces.append(
                EllipseCurve(
                    curve.center,
                    curve.major_radius,
                    curve.minor_radius,
                    curve.rotation_deg,
                    curve.start_deg + start * curve.sweep_deg,
                    (end - start) * curve.sweep_deg,
                )
            )
    return tuple(pieces)


def _spline(curve: SplineCurve) -> Geom2d_BSplineCurve:
    poles = TColgp_Array1OfPnt2d(1, len(curve.poles))
    weights = TColStd_Array1OfReal(1, len(curve.weights))
    knots = TColStd_Array1OfReal(1, len(curve.knots))
    multiplicities = TColStd_Array1OfInteger(1, len(curve.multiplicities))
    for index, ((x, y), weight) in enumerate(zip(curve.poles, curve.weights, strict=True), 1):
        poles.SetValue(index, gp_Pnt2d(x, y))
        weights.SetValue(index, weight)
    for index, (knot, multiplicity) in enumerate(
        zip(curve.knots, curve.multiplicities, strict=True), 1
    ):
        knots.SetValue(index, knot)
        multiplicities.SetValue(index, multiplicity)
    return Geom2d_BSplineCurve(poles, weights, knots, multiplicities, curve.degree, curve.periodic)


def _clip_spline(curve: SplineCurve, region: DetailRegion) -> tuple[CurveGeometry, ...]:
    if curve.periodic:
        raise ValueError("穿过详图边界的周期样条暂不支持")
    spline = _spline(curve)
    circle = Geom2d_Circle(gp_Ax2d(gp_Pnt2d(*region.center), gp_Dir2d(1, 0)), region.radius)
    intersection = Geom2dAPI_InterCurveCurve(spline, circle, 1e-9)
    algorithm = intersection.Intersector()
    if not algorithm.IsDone() or intersection.NbSegments():
        raise ValueError("详图边界与样条相切或重合，暂不能安全裁剪")
    first, last = spline.FirstParameter(), spline.LastParameter()
    cuts = [first, last]
    for index in range(1, intersection.NbPoints() + 1):
        parameter = algorithm.Point(index).ParamOnFirst()
        if first + 1e-12 < parameter < last - 1e-12:
            cuts.append(parameter)
    cuts = sorted(set(cuts))
    pieces: list[CurveGeometry] = []
    for start, end in zip(cuts, cuts[1:], strict=False):
        if end - start <= 1e-12:
            continue
        point = spline.Value((start + end) / 2)
        gap = dist((point.X(), point.Y()), region.center)
        if abs(gap - region.radius) <= 1e-9 * max(1, region.radius):
            raise ValueError("详图边界与样条的关系不明确，请调整详图范围")
        if gap < region.radius:
            segment = _spline(curve)
            segment.Segment(start, end, 1e-9)
            points = tuple(segment.Pole(i) for i in range(1, segment.NbPoles() + 1))
            pieces.append(
                SplineCurve(
                    tuple((point.X(), point.Y()) for point in points),
                    segment.Degree(),
                    tuple(segment.Knot(i) for i in range(1, segment.NbKnots() + 1)),
                    tuple(segment.Multiplicity(i) for i in range(1, segment.NbKnots() + 1)),
                    tuple(segment.Weight(i) for i in range(1, segment.NbPoles() + 1)),
                    segment.IsPeriodic(),
                )
            )
    return tuple(pieces)
