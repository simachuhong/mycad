# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Surface extension follows the supporting line or circular arc."""

from uuid import uuid4

import pytest

from mycad.core.geometric_tolerance_surface_extension import surface_extension_geometry
from mycad.core.sketch import ArcEntity, LineEntity


@pytest.mark.parametrize(
    ("side", "target", "start", "end"),
    [
        ("end", (15, 0), (11, 0), (17, 0)),
        ("start", (-5, 0), (-1, 0), (-7, 0)),
    ],
)
def test_line_surface_extension_follows_selected_end(side, target, start, end):
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    result = surface_extension_geometry(line, side, 5, 1, 2)
    assert result.target_mm == pytest.approx(target)
    assert result.start_mm == pytest.approx(start)
    assert result.end_mm == pytest.approx(end)
    assert result.center_mm is None


def test_arc_surface_extension_respects_clockwise_sweep():
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 90, -90)
    result = surface_extension_geometry(arc, "end", 5 * 3.141592653589793 / 9, 0, 0)
    assert result.target_mm == pytest.approx((9.8480775301, -1.7364817767))
    assert result.center_mm == (0, 0)
    assert result.sweep_angle_deg == pytest.approx(-10)


def test_surface_extension_rejects_invalid_lengths():
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    for values in ((0, 0, 0), (1, -1, 0), (1, 0, float("inf")), (1, 2, 0)):
        with pytest.raises(ValueError):
            surface_extension_geometry(line, "end", *values)


def test_extension_attachment_roundtrip_and_follows_line():
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    spec = SurfaceExtensionSpec("end", 5, 1, 2)
    attachment = DatumAttachment(
        uuid4().hex,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=spec,
    )
    assert DatumAttachment.from_mapping(attachment.to_mapping()) == attachment
    changed = LineEntity(line.entity_id, (0, 0), (0, 20))
    assert resolve_attachment_local(attachment, {line.entity_id: changed}) == pytest.approx((0, 25))


def test_extension_distances_reject_unrepresentable_number():
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec

    with pytest.raises(ValueError):
        SurfaceExtensionSpec("end", 10**1000, 0, 0)
