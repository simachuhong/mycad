# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Resolve stable sketch point references without a UI or CAD backend."""

from uuid import uuid4

import pytest

from mycad.core.sketch import ArcEntity, LineEntity, PointEntity, PolylineEntity
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.core.sketch_references import resolve_point_reference


def test_point_references_track_current_source_geometry() -> None:
    identity = uuid4().hex
    ref = SketchGeometryReference(identity, "vertex", 0)
    assert resolve_point_reference(ref, {identity: PointEntity(identity, (3, 7))}) == (3, 7)
    assert resolve_point_reference(ref, {identity: PointEntity(identity, (8, 9))}) == (8, 9)
    assert resolve_point_reference(ref, {}) is None
    assert (
        resolve_point_reference(
            SketchGeometryReference(identity, "vertex", 1),
            {identity: PointEntity(identity, (3, 7))},
        )
        is None
    )


def test_line_polyline_and_arc_references() -> None:
    identity = uuid4().hex
    line = LineEntity(identity, (1, 2), (3, 4))
    assert resolve_point_reference(SketchGeometryReference(identity, "end"), {identity: line}) == (
        3,
        4,
    )
    polyline = PolylineEntity(identity, ((0, 0), (1, 1), (2, 0)))
    assert resolve_point_reference(
        SketchGeometryReference(identity, "vertex", 2), {identity: polyline}
    ) == (2, 0)
    assert (
        resolve_point_reference(
            SketchGeometryReference(identity, "vertex", 3), {identity: polyline}
        )
        is None
    )
    arc = ArcEntity(identity, (1, 2), 2, 0, 90)
    assert resolve_point_reference(SketchGeometryReference(identity, "end"), {identity: arc}) == (
        pytest.approx((1, 4))
    )
