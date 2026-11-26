# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF preserves point identities only while their source geometry is verifiable."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import ezdxf.filemanagement as filemanagement
import pytest
from ezdxf.document import Drawing

from mycad.core.geometric_tolerance import (
    DatumAttachment,
    DatumIdentifier,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.core.geometric_tolerance_topology import new_curve_point_identities
from mycad.core.sketch import PolylineEntity, Sketch, SplineEntity, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

_read_file = cast("Callable[[Path], Drawing]", vars(filemanagement)["readfile"])
_save_file = cast("Callable[[Drawing, Path], None]", vars(Drawing)["saveas"])


def test_reordered_identity_dxf_import_commits_and_reopens(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    identity = uuid4().hex
    ids = new_curve_point_identities(identity, "polyline", 3)
    curve = PolylineEntity(identity, ((10, 10), (10, 0), (0, 0)), point_ids=tuple(reversed(ids)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (12, 12),
        (10, 10),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(identity, "vertex", 0)
        ),
    )
    path = tmp_path / "reordered.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    app.commit_new_sketch(
        services,
        loaded,
        imported.sketch,
        session_identity=0,
        imported_datums=imported.datum_identifiers,
        imported_curve_ids=True,
    )
    assert services.kernel.sketches[0].entities == (curve,)
    assert services.kernel.drawing_datum_identifiers[0].attachment == datum.attachment
    saved = tmp_path / "reopened.my2d"
    save_document(loaded.document, saved)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, saved)
    assert reopened.kernel.sketches[0].entities == (curve,)
    assert reopened.kernel.drawing_datum_identifiers[0].attachment == datum.attachment


def test_dxf_curve_point_ids_and_attached_datum_roundtrip(tmp_path: Path) -> None:
    entity_id = uuid4().hex
    ids = new_curve_point_identities(entity_id, "polyline", 4)
    curve = PolylineEntity(entity_id, ((0, 0), (10, 0), (10, 10), (20, 10)), point_ids=ids)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entity_id, "vertex", 0)
        ),
    )
    path = tmp_path / "identity.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    imported = read_sketch_dxf(path)
    assert imported.sketch.entities == (curve,)
    assert imported.datum_identifiers[0].attachment == datum.attachment


def test_dxf_modified_curve_loses_point_ids_and_datum_attachment(tmp_path: Path) -> None:
    entity_id = uuid4().hex
    ids = new_curve_point_identities(entity_id, "polyline", 4)
    curve = PolylineEntity(entity_id, ((0, 0), (10, 0), (10, 10), (20, 10)), point_ids=ids)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entity_id, "vertex", 0)
        ),
    )
    path = tmp_path / "modified.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    document = _read_file(path)
    native = cast("Any", document.modelspace().query("LWPOLYLINE").first)
    native.set_points(((0, 0), (10, 10), (10, 0), (20, 10)), format="xy")
    _save_file(document, path)
    imported = read_sketch_dxf(path)
    changed = imported.sketch.entities[0]
    assert isinstance(changed, PolylineEntity) and not changed.point_ids
    assert imported.datum_identifiers[0].attachment is None
    assert any("点身份" in warning for warning in imported.report.warnings)


def test_dxf_missing_identity_metadata_does_not_restore_attachment(tmp_path: Path) -> None:
    from mycad.formats.dxf_curve_identity import CURVE_IDENTITY_APPID

    identity = uuid4().hex
    ids = new_curve_point_identities(identity, "polyline", 3)
    curve = PolylineEntity(identity, ((0, 0), (10, 0), (10, 10)), point_ids=ids)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(identity, "vertex", 0)
        ),
    )
    path = tmp_path / "missing-metadata.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    document = _read_file(path)
    native = cast("Any", document.modelspace().query("LWPOLYLINE").first)
    native.discard_xdata(CURVE_IDENTITY_APPID)
    _save_file(document, path)
    imported = read_sketch_dxf(path)
    assert imported.datum_identifiers[0].attachment is None
    assert any("点身份" in warning for warning in imported.report.warnings)


def test_dxf_identity_snapshot_scales_with_drawing_units(tmp_path: Path) -> None:
    identity = uuid4().hex
    ids = new_curve_point_identities(identity, "polyline", 3)
    curve = PolylineEntity(identity, ((0, 0), (1, 0), (1, 2)), point_ids=ids)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    path = tmp_path / "inch.dxf"
    write_sketches_dxf((sketch,), path)
    document = _read_file(path)
    document.header["$INSUNITS"] = 1
    _save_file(document, path)
    imported = read_sketch_dxf(path)
    found = imported.sketch.entities[0]
    assert isinstance(found, PolylineEntity)
    assert found.point_ids == ids
    assert found.points_mm == ((0, 0), (25.4, 0), (25.4, 50.8))


def test_dxf_repeated_curve_points_detach_ambiguous_identity(tmp_path: Path) -> None:
    identity = uuid4().hex
    ids = new_curve_point_identities(identity, "polyline", 4)
    curve = PolylineEntity(identity, ((0, 0), (1, 0), (0, 0), (0, 1)), point_ids=ids)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(identity, "vertex", 0)
        ),
    )
    path = tmp_path / "ambiguous.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    imported = read_sketch_dxf(path)
    found = imported.sketch.entities[0]
    assert isinstance(found, PolylineEntity) and not found.point_ids
    assert imported.datum_identifiers[0].attachment is None
    assert any("点身份" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("modified", [False, True])
def test_dxf_spline_point_identities_checked_against_control_points(
    tmp_path: Path, modified: bool
) -> None:
    identity = uuid4().hex
    ids = new_curve_point_identities(identity, "spline", 4)
    spline = SplineEntity(identity, ((0, 0), (10, 0), (10, 10), (20, 10)), point_ids=ids)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (0, 0),
        attachment=DatumAttachment(sketch.sketch_id, SketchGeometryReference(identity, "start")),
    )
    path = tmp_path / "spline.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    if modified:
        document = _read_file(path)
        native = cast("Any", document.modelspace().query("SPLINE").first)
        native.control_points[1] = (11, 0, 0)
        _save_file(document, path)
    imported = read_sketch_dxf(path)
    found = imported.sketch.entities[0]
    assert isinstance(found, SplineEntity)
    assert found.point_ids == (() if modified else ids)
    assert (imported.datum_identifiers[0].attachment is None) == modified


def test_dxf_duplicate_curve_point_ids_detach_both_ambiguous_curves(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad.formats.dxf_curve_identity import CURVE_IDENTITY_APPID, pack_curve_identities

    first_id, second_id = uuid4().hex, uuid4().hex
    first_ids = new_curve_point_identities(first_id, "polyline", 3)
    first = PolylineEntity(first_id, ((0, 0), (10, 0), (10, 10)), point_ids=first_ids)
    second = PolylineEntity(
        second_id,
        ((20, 0), (30, 0), (30, 10)),
        point_ids=new_curve_point_identities(second_id, "polyline", 3),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(first_id, "vertex", 0)
        ),
    )
    path = tmp_path / "duplicated.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    document = _read_file(path)
    native = cast("Any", list(document.modelspace().query("LWPOLYLINE"))[1])
    parts = pack_curve_identities(replace(second, point_ids=first_ids))
    native.set_xdata(CURVE_IDENTITY_APPID, [(1000, part) for part in parts])
    _save_file(document, path)
    imported = read_sketch_dxf(path)
    assert all(
        isinstance(item, PolylineEntity) and not item.point_ids for item in imported.sketch.entities
    )
    assert imported.datum_identifiers[0].attachment is None
    assert any("点身份重复" in warning for warning in imported.report.warnings)


def test_dxf_forged_curve_identity_is_detached_before_document_import(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.formats.dxf_curve_identity import CURVE_IDENTITY_APPID, pack_curve_identities

    identity = uuid4().hex
    curve = PolylineEntity(
        identity,
        ((0, 0), (10, 0), (10, 10)),
        point_ids=new_curve_point_identities(identity, "polyline", 3),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(identity, "vertex", 0)
        ),
    )
    path = tmp_path / "forged.dxf"
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (5, 5),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=datum.attachment,
    )
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,), tolerance_frames=(frame,))
    document = _read_file(path)
    native = cast("Any", document.modelspace().query("LWPOLYLINE").first)
    forged = replace(curve, point_ids=tuple(uuid4().hex for _ in range(3)))
    native.set_xdata(CURVE_IDENTITY_APPID, [(1000, part) for part in pack_curve_identities(forged)])
    _save_file(document, path)
    imported = read_sketch_dxf(path)
    found = imported.sketch.entities[0]
    assert isinstance(found, PolylineEntity) and not found.point_ids
    assert imported.datum_identifiers[0].attachment is None
    assert imported.tolerance_frames[0].leader_attachment is None
    assert any("点身份" in warning for warning in imported.report.warnings)
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    app.commit_new_sketch(
        services,
        loaded,
        imported.sketch,
        session_identity=0,
        imported_datums=imported.datum_identifiers,
        imported_tolerance_frames=imported.tolerance_frames,
        imported_curve_ids=True,
    )
    assert services.kernel.sketches[0].entities == (found,)
    assert services.kernel.drawing_datum_identifiers[0].attachment is None
    assert services.kernel.drawing_tolerance_frames[0].leader_attachment is None


def test_dxf_deeply_nested_identity_metadata_does_not_abort_import(tmp_path: Path) -> None:
    from mycad.formats.dxf_curve_identity import CURVE_IDENTITY_APPID

    identity = uuid4().hex
    curve = PolylineEntity(
        identity,
        ((0, 0), (10, 0), (10, 10)),
        point_ids=new_curve_point_identities(identity, "polyline", 3),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(identity, "vertex", 0)
        ),
    )
    path = tmp_path / "nested.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    document = _read_file(path)
    native = cast("Any", document.modelspace().query("LWPOLYLINE").first)
    malformed = "[" * 2000 + "0" + "]" * 2000
    native.set_xdata(
        CURVE_IDENTITY_APPID,
        [(1000, malformed[index : index + 240]) for index in range(0, len(malformed), 240)],
    )
    _save_file(document, path)
    imported = read_sketch_dxf(path)
    found = imported.sketch.entities[0]
    assert isinstance(found, PolylineEntity) and not found.point_ids
    assert imported.datum_identifiers[0].attachment is None
    assert any("点身份" in warning for warning in imported.report.warnings)
