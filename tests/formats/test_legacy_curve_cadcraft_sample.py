# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Check the external resave of the delivered legacy-curve sample."""

from pathlib import Path

from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
from mycad.core.sketch import PolylineEntity, SplineEntity
from mycad.formats.providers.dxf_provider import read_sketch_dxf


def test_cadcraft_resaved_legacy_curve_sample_retains_verified_attachments() -> None:
    path = (
        Path(__file__).parents[2]
        / ".omo/evidence/tolerance-legacy-curve-upgrade/cadcraft-resaved.dxf"
    )
    imported = read_sketch_dxf(path)
    entities = {entity.entity_id: entity for entity in imported.sketch.entities}
    polyline = next(entity for entity in entities.values() if isinstance(entity, PolylineEntity))
    spline = next(entity for entity in entities.values() if isinstance(entity, SplineEntity))
    assert len(polyline.point_ids) == 3
    assert len(spline.point_ids) == 4
    datum = imported.datum_identifiers[0]
    frame = imported.tolerance_frames[0]
    assert datum.attachment is not None and frame.leader_attachment is not None
    assert resolve_attachment_local(datum.attachment, entities) == (30, 0)
    assert resolve_attachment_local(frame.leader_attachment, entities) == (15, 0)
    assert any("引线原生关联缺失" in warning for warning in imported.report.warnings)


def test_cadcraft_moved_curve_detaches_sample_annotations() -> None:
    path = (
        Path(__file__).parents[2]
        / ".omo/evidence/tolerance-legacy-curve-upgrade/cadcraft-moved-curve.dxf"
    )
    imported = read_sketch_dxf(path)
    polyline = next(e for e in imported.sketch.entities if isinstance(e, PolylineEntity))
    spline = next(e for e in imported.sketch.entities if isinstance(e, SplineEntity))
    assert polyline.points_mm == ((5, 0), (35, 0), (35, 15))
    assert not polyline.point_ids and len(spline.point_ids) == 4
    datum = imported.datum_identifiers[0]
    frame = imported.tolerance_frames[0]
    assert datum.attachment is None and datum.target_mm == (30, 0)
    assert frame.leader_attachment is None and frame.leader_target_mm == (15, 0)
    assert any("曲线点顺序或坐标已改变" in warning for warning in imported.report.warnings)
    assert any("引线附着无法恢复" in warning for warning in imported.report.warnings)
    assert any("基准 A 的附着目标" in warning for warning in imported.report.warnings)
