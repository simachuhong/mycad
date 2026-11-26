# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Geometric annotations are transactional drawing history."""

from dataclasses import replace
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.exceptions import ValidationError
from mycad.core.geometric_tolerance import (
    DatumIdentifier,
    DatumReference,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.core.persistence import save_document
from mycad.core.sketch import Sketch, WorkPlaneFrame
from mycad.core.sketch_layers import SketchLayer
from mycad.formats.providers.dxf_provider import DXF_PROVIDER, DxfExchangeReport


def test_bent_datum_survives_history_and_save(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0), leader_offsets=((-5, -5),))
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=7
        )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=8
    )
    assert loaded.document.commands[-1].version == 8
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_datum_identifiers
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    path = tmp_path / "bent.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)


def test_frame_leader_requires_version_nine_and_replays(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2),), (10, 10), leader_target_mm=(0, 0)
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local", version=8
        )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local", version=9
    )
    assert loaded.document.commands[-1].version == 9
    path = tmp_path / "frame-leader.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (frame,)


def test_previous_datum_command_version_still_replays() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=7
    )
    loaded.bus.undo_operation()
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_datum_without_leader_requires_version_eleven_and_replays(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 2), leader_visible=False)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=10
        )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    path = tmp_path / "no-leader.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)


def test_shared_datum_layout_requires_version_twelve_and_replays(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0), layout_mode="shared")
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=11
        )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    path = tmp_path / "shared-datum.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("kind", ("datum", "frame"))
def test_ellipse_annotation_attachment_rejects_old_history_versions(kind: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    attachment = DatumAttachment(
        uuid4().hex, SketchGeometryReference(uuid4().hex, "geometry"), 0.25, curve_kind="ellipse"
    )
    if kind == "datum":
        datum = DatumIdentifier(uuid4().hex, "A", (2, 3), (0, 0), attachment=attachment)
        params = {"add_datums": [datum.to_mapping()]}
    else:
        frame = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (2, 3),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
        )
        params = {"add_frames": [frame.to_mapping()]}
    with pytest.raises(ValidationError, match="版本 13"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=12)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_indication_arrow_size_requires_version_18(tmp_path: Path, owner: str) -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    indication = SurfaceIndication((5, 5), (10, 5), 0.5, arrow_size_mm=5)
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), surface_indication=indication)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        surface_indication=indication,
    )
    params = (
        {"add_datums": [datum.to_mapping()]}
        if owner == "datum"
        else {"add_frames": [frame.to_mapping()]}
    )
    with pytest.raises(ValidationError, match="版本 18"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=17)
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=18)
    assert loaded.document.commands[-1].version == 18
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_datum_identifiers
    assert not services.kernel.drawing_tolerance_frames
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == ((datum,) if owner == "datum" else ())
    assert services.kernel.drawing_tolerance_frames == ((frame,) if owner == "frame" else ())
    path = tmp_path / "surface-arrow.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == ((datum,) if owner == "datum" else ())
    assert reopened.kernel.drawing_tolerance_frames == ((frame,) if owner == "frame" else ())


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_normal_requires_version_20(owner: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    surface = SurfaceIndication((5, 5), (10, 5), 0.5, ((0, 3),), auto_normal=True)
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 20), (0, 0), attachment=attachment, surface_indication=surface
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_attachment=attachment,
        surface_indication=surface,
    )
    params = (
        {"add_datums": [datum.to_mapping()]}
        if owner == "datum"
        else {"add_frames": [frame.to_mapping()]}
    )
    with pytest.raises(ValidationError, match="版本 20"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=19)
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=20)
    assert loaded.document.commands[-1].version == 20


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("enabled", [False, True])
def test_surface_normal_follows_geometry_and_preserves_legacy(
    tmp_path: Path, owner: str, enabled: bool
) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    surface = SurfaceIndication((5, 8), (10, 8), 0.5, ((0, 3),), auto_normal=enabled)
    datum = DatumIdentifier(
        uuid4().hex, "A", (30, 30), (10, 0), attachment=attachment, surface_indication=surface
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (30, 30),
        leader_target_mm=(10, 0),
        leader_attachment=attachment,
        surface_indication=surface,
    )
    params = (
        {"add_datums": [datum.to_mapping()]}
        if owner == "datum"
        else {"add_frames": [frame.to_mapping()]}
    )
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=20 if enabled else 19)
    changed = replace(sketch, entities=(replace(line, end_mm=(20, 20)),))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    result = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert result.surface_indication is not None
    expected = (-3 / math.sqrt(2), 3 / math.sqrt(2)) if enabled else (0, 3)
    assert result.surface_indication.leader_offsets_mm[0] == pytest.approx(expected)
    loaded.bus.undo_operation()
    previous = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert previous.surface_indication == surface
    loaded.bus.redo_operation()
    path = tmp_path / "surface-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    reopened_item = (
        reopened.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames[0]
    )
    assert reopened_item == result


def test_surface_normal_rejects_colliding_vertex_revision_atomically() -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    surface = SurfaceIndication(
        (5, 8), (10, 8), 0.5, ((0, 3), (-3 / math.sqrt(2), 3 / math.sqrt(2))), auto_normal=True
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (30, 30), (10, 0), attachment=attachment, surface_indication=surface
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    count = loaded.document.command_count
    changed = replace(sketch, entities=(replace(line, end_mm=(20, 20)),))
    state = changed.to_state_mapping()
    with pytest.raises(ValidationError, match="顶点重合"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_normal_follows_spline_revision(owner: str) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_normal
    from mycad.core.sketch import SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    spline = SplineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(spline.entity_id, "geometry"),
        0.5,
        curve_kind="spline",
        control_count=4,
    )
    surface = SurfaceIndication((5, 8), (10, 8), 0.5, ((-2, 2),), auto_normal=True)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (30, 30),
        spline.point_at(0.5),
        attachment=attachment,
        surface_indication=surface,
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (30, 30),
        leader_target_mm=spline.point_at(0.5),
        leader_attachment=attachment,
        surface_indication=surface,
    )
    params = (
        {"add_datums": [datum.to_mapping()]}
        if owner == "datum"
        else {"add_frames": [frame.to_mapping()]}
    )
    loaded.bus.execute("drawing.tolerance.batch", params, "local")
    changed = replace(
        sketch, entities=(replace(spline, control_points_mm=((0, 0), (10, 0), (15, 10), (20, 10))),)
    )
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    updated = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert updated.surface_indication is not None
    target = updated.target_mm if isinstance(updated, DatumIdentifier) else updated.leader_target_mm
    assert target is not None
    normal = resolve_attachment_normal(attachment, changed, target, enable_spline=True)
    assert normal is not None
    x, y = updated.surface_indication.leader_offsets_mm[0]
    assert math.hypot(x, y) == pytest.approx(math.sqrt(8))
    assert x * normal[1] - y * normal[0] == pytest.approx(0, abs=1e-9)
    loaded.bus.undo_operation()
    previous = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert previous.surface_indication == surface


def test_surface_normal_rejects_degenerate_spline_revision() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.sketch import SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    spline = SplineEntity(uuid4().hex, ((0, 0), (5, 0), (10, 5), (15, 0)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(spline.entity_id, "geometry"),
        0,
        curve_kind="spline",
        control_count=4,
    )
    surface = SurfaceIndication((5, 8), (10, 8), 0.5, ((0, 3),), auto_normal=True)
    datum = DatumIdentifier(
        uuid4().hex, "A", (30, 30), (0, 0), attachment=attachment, surface_indication=surface
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    count = loaded.document.command_count
    changed = replace(
        sketch, entities=(replace(spline, control_points_mm=((0, 0), (0, 0), (10, 5), (15, 0))),)
    )
    state = changed.to_state_mapping()
    with pytest.raises(ValidationError, match="无法确定附着法向"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("enabled", [False, True])
def test_frame_primary_normal_follows_geometry_and_history(tmp_path: Path, enabled: bool) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (30, 30),
        leader_target_mm=(10, 0),
        leader_offsets=((-20, -27),),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        leader_auto_normal=enabled,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()]},
        "local",
        version=21 if enabled else 20,
    )
    changed = replace(sketch, entities=(replace(line, end_mm=(20, 20)),))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    updated = services.kernel.drawing_tolerance_frames[0]
    assert updated.leader_target_mm == (10, 10)
    vertex = (
        updated.position_mm[0] + updated.leader_offsets[-1][0],
        updated.position_mm[1] + updated.leader_offsets[-1][1],
    )
    expected = (10 - 3 / math.sqrt(2), 10 + 3 / math.sqrt(2)) if enabled else (10, 3)
    assert vertex == pytest.approx(expected)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    path = tmp_path / "frame-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (updated,)


@pytest.mark.parametrize("move_target", [False, True])
def test_mixed_move_preserves_frame_normal_vertex(move_target: bool) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    other = LineEntity(uuid4().hex, (0, 40), (20, 40))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target, other))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(target.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(10, 0),
        leader_offsets=((-3, -4), (-10, -17)),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    app.move_tolerance_selection(
        services,
        loaded,
        (target.entity_id if move_target else other.entity_id,),
        (frame.frame_id,),
        (),
        (),
        (0, -30),
        session_identity=0,
    )
    moved = services.kernel.drawing_tolerance_frames[0]
    vertices = tuple(
        (moved.position_mm[0] + x, moved.position_mm[1] + y) for x, y in moved.leader_offsets
    )
    assert vertices == (((17, -14), (10, -27)) if move_target else ((17, 16), (10, 3)))
    assert moved.leader_auto_normal
    loaded.bus.undo_operation()
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_tolerance_frames == (moved,)


def test_versioned_datum_normal_rejects_coincident_leader_vertices() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-14, -10), (-10, -6)),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(sketch, entities=(replace(line, end_mm=(0, 10)),))
    state = changed.to_state_mapping()
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="顶点重合"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
            version=56,
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_versioned_datum_normal_rejects_degenerate_spline_revision() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    spline = SplineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(spline.entity_id, "geometry"),
        0,
        curve_kind="spline",
        control_count=4,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 0),
        attachment=attachment,
        leader_offsets=((-20, -16),),
        leader_auto_normal=True,
        spline_normal_enabled=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(
        sketch, entities=(replace(spline, control_points_mm=((0, 0), (0, 0), (10, 10), (20, 10))),)
    )
    state = changed.to_state_mapping()
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="法向"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
            version=56,
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("degenerate", [False, True])
def test_frame_primary_spline_normal_revision(degenerate: bool) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_normal
    from mycad.core.sketch import SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    spline = SplineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    parameter = 0.0 if degenerate else 0.5
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(spline.entity_id, "geometry"),
        parameter,
        curve_kind="spline",
        control_count=4,
    )
    target = spline.point_at(parameter)
    normal = resolve_attachment_normal(attachment, sketch, target, enable_spline=True)
    assert normal is not None
    position = (30.0, 30.0)
    vertex = (target[0] + 3 * normal[0], target[1] + 3 * normal[1])
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        position,
        leader_target_mm=target,
        leader_offsets=((vertex[0] - 30, vertex[1] - 30),),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    new_points = (
        ((0, 0), (0, 0), (10, 10), (20, 10))
        if degenerate
        else ((0, 0), (10, 0), (15, 10), (20, 10))
    )
    changed = replace(sketch, entities=(replace(spline, control_points_mm=new_points),))
    state = changed.to_state_mapping()
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ]
    }
    if degenerate:
        count = loaded.document.command_count
        with pytest.raises(ValidationError, match="无法确定附着法向"):
            loaded.bus.execute("drawing.sketch.revise", params, "local")
        assert loaded.document.command_count == count and services.kernel.sketches == (sketch,)
        assert services.kernel.drawing_tolerance_frames == (frame,)
    else:
        loaded.bus.execute("drawing.sketch.revise", params, "local")
        updated = services.kernel.drawing_tolerance_frames[0]
        assert updated.leader_target_mm is not None
        new_normal = resolve_attachment_normal(
            attachment, changed, updated.leader_target_mm, enable_spline=True
        )
        assert new_normal is not None
        vector = (
            updated.position_mm[0] + updated.leader_offsets[-1][0] - updated.leader_target_mm[0],
            updated.position_mm[1] + updated.leader_offsets[-1][1] - updated.leader_target_mm[1],
        )
        assert math.hypot(*vector) == pytest.approx(3)
        assert vector[0] * new_normal[1] - vector[1] * new_normal[0] == pytest.approx(0, abs=1e-9)
        loaded.bus.undo_operation()
        assert services.kernel.drawing_tolerance_frames == (frame,)


def test_frame_primary_normal_rejects_colliding_vertex_revision() -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    collision = (10 - 3 / math.sqrt(2), 10 + 3 / math.sqrt(2))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (30, 30),
        leader_target_mm=(10, 0),
        leader_offsets=((collision[0] - 30, collision[1] - 30), (-20, -27)),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    count = loaded.document.command_count
    changed = replace(sketch, entities=(replace(line, end_mm=(20, 20)),))
    state = changed.to_state_mapping()
    with pytest.raises(ValidationError, match="顶点重合"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_frame_primary_normal_requires_version_21() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((-20, -17),),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    with pytest.raises(ValidationError, match="版本 21"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local", version=20
        )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    assert loaded.document.commands[-1].version == 29


def test_spline_normal_flag_requires_version_19() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), spline_normal_enabled=True)
    with pytest.raises(ValidationError, match="版本 19"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=18
        )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=19
    )
    assert loaded.document.commands[-1].version == 19
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("enabled", [False, True])
def test_spline_normal_revision_replay_and_legacy_behavior(tmp_path: Path, enabled: bool) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_normal
    from mycad.core.sketch import SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    spline = SplineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(spline.entity_id, "geometry"),
        0.5,
        curve_kind="spline",
        control_count=4,
    )
    target = spline.point_at(0.5)
    normal = resolve_attachment_normal(attachment, sketch, target, enable_spline=True)
    assert normal is not None
    position = (30.0, 30.0)
    vertex = (target[0] + 3 * normal[0], target[1] + 3 * normal[1])
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        position,
        target,
        attachment=attachment,
        leader_offsets=((vertex[0] - position[0], vertex[1] - position[1]),),
        leader_auto_normal=True,
        spline_normal_enabled=enabled,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()]},
        "local",
        version=19 if enabled else 18,
    )
    changed_spline = replace(spline, control_points_mm=((0, 0), (10, 0), (15, 10), (20, 10)))
    changed = replace(sketch, entities=(changed_spline,))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    updated = services.kernel.drawing_datum_identifiers[0]
    if enabled:
        new_normal = resolve_attachment_normal(
            attachment, changed, updated.target_mm, enable_spline=True
        )
        assert new_normal is not None
        vector = (
            updated.position_mm[0] + updated.leader_offsets[-1][0] - updated.target_mm[0],
            updated.position_mm[1] + updated.leader_offsets[-1][1] - updated.target_mm[1],
        )
        assert math.hypot(*vector) == pytest.approx(3)
        assert vector[0] * new_normal[1] - vector[1] * new_normal[0] == pytest.approx(0, abs=1e-9)
    else:
        assert updated.leader_offsets == datum.leader_offsets
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated,)
    path = tmp_path / "spline-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)


@pytest.mark.parametrize("move_target", [False, True])
def test_mixed_move_keeps_normal_datum_vertex_on_correct_side(
    tmp_path: Path, move_target: bool
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    other = LineEntity(uuid4().hex, (0, 40), (20, 40))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target, other))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (10, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(target.entity_id, "geometry"), 0.5
        ),
        leader_offsets=((-3, -4), (-10, -17)),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    app.move_tolerance_selection(
        services,
        loaded,
        (target.entity_id if move_target else other.entity_id,),
        (),
        (datum.datum_id,),
        (),
        (0, -30),
        session_identity=0,
    )
    moved = services.kernel.drawing_datum_identifiers[0]
    expected = ((17, -14), (10, -27)) if move_target else ((17, 16), (10, 3))
    actual = tuple(
        (moved.position_mm[0] + x, moved.position_mm[1] + y) for x, y in moved.leader_offsets
    )
    assert actual == expected
    assert moved.leader_auto_normal
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (moved,)
    path = tmp_path / "normal-mixed-move.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (moved,)


def test_imported_spline_normal_datum_remains_associated(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    spline = SplineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(spline.entity_id, "geometry"),
        0.5,
        curve_kind="spline",
        control_count=4,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (30, 30),
        spline.point_at(0.5),
        attachment=attachment,
        leader_offsets=((-22, -23),),
        leader_auto_normal=True,
        spline_normal_enabled=True,
    )
    path = tmp_path / "spline-normal.dxf"
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
    )
    restored = services.kernel.drawing_datum_identifiers[0]
    assert restored.spline_normal_enabled and restored.leader_auto_normal
    assert restored.attachment is not None
    assert restored.attachment.sketch_id == services.kernel.sketches[0].sketch_id
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_datum_identifiers
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (restored,)


def test_surface_indication_requires_new_command_version(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    indication = SurfaceIndication((5, 5), (10, 5), 0.5)
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), surface_indication=indication)
    with pytest.raises(ValidationError, match="版本 17"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=16
        )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=17
    )
    assert services.kernel.drawing_datum_identifiers == (datum,)
    path = tmp_path / "surface-indication.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)


def test_surface_indication_tracks_attached_geometry_and_undo() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.geometric_tolerance_geometry import surface_indication_geometry
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    indication = SurfaceIndication((3, 8), (8, 8), 0.5)
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 20), (5, 0), attachment=attachment, surface_indication=indication
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(sketch, entities=(replace(line, end_mm=(20, 0)),))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=55,
    )
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.target_mm == pytest.approx((10, 0))
    assert updated.surface_indication == indication
    assert surface_indication_geometry(updated.target_mm, indication)[0] == ((13, 8), (18, 8))
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_surface_extension_requires_new_command_version() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (15, 0), attachment=attachment)
    with pytest.raises(ValidationError, match="版本 16"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=15
        )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=16
    )
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx((15, 0))


def test_surface_extension_follows_revision_undo_and_reopen(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (15, 0), attachment=attachment)
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=16
    )
    changed = replace(sketch, entities=(replace(line, end_mm=(0, 20)),))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=55,
    )
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx((0, 25))
    path = tmp_path / "surface-extension.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx((0, 25))
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx((15, 0))


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_arc_surface_extension_follows_rotation_and_replays(tmp_path: Path, owner: str) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import ArcEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 90, -90)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(arc.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 10 * math.pi / 18, 0, 0),
    )
    initial = (10 * math.cos(math.radians(10)), -10 * math.sin(math.radians(10)))
    if owner == "datum":
        datum = DatumIdentifier(uuid4().hex, "A", (20, 20), initial, attachment=attachment)
        params = {"add_datums": [datum.to_mapping()]}
    else:
        frame = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (20, 20),
            leader_target_mm=initial,
            leader_attachment=attachment,
        )
        params = {"add_frames": [frame.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=16)

    changed = replace(sketch, entities=(replace(arc, start_angle_deg=180),))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=55,
    )

    def target(current: app.AppServices) -> tuple[float, float] | None:
        if owner == "datum":
            return current.kernel.drawing_datum_identifiers[0].target_mm
        return current.kernel.drawing_tolerance_frames[0].leader_target_mm

    expected = (10 * math.sin(math.radians(10)), 10 * math.cos(math.radians(10)))
    assert target(services) == pytest.approx(expected)
    loaded.bus.undo_operation()
    assert target(services) == pytest.approx(initial)
    loaded.bus.redo_operation()
    assert target(services) == pytest.approx(expected)
    path = tmp_path / f"arc-extension-{owner}.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert target(reopened) == pytest.approx(expected)


def test_annotation_attachment_follows_frame_and_rejects_cycle(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    rows = (ToleranceRow("position", 0.1, 2),)
    source = FeatureControlFrame(uuid4().hex, rows, (10, 10))
    ref = AnnotationAttachment("frame", source.frame_id, (2, 0))
    dependent = FeatureControlFrame(
        uuid4().hex, rows, (30, 30), leader_target_mm=(12, 10), leader_annotation_attachment=ref
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (12, 10), annotation_attachment=ref)
    payload = {
        "add_frames": [source.to_mapping(), dependent.to_mapping()],
        "add_datums": [datum.to_mapping()],
    }
    with pytest.raises(ValidationError, match="版本 14"):
        loaded.bus.execute("drawing.tolerance.batch", payload, "local", version=13)
    loaded.bus.execute("drawing.tolerance.batch", payload, "local")
    rotated = replace(source, position_mm=(15, 20), rotation_deg=90)
    loaded.bus.execute(
        "drawing.tolerance.batch", {"update_frames": [rotated.to_mapping()]}, "local"
    )
    frames = {item.frame_id: item for item in services.kernel.drawing_tolerance_frames}
    assert frames[dependent.frame_id].leader_target_mm == pytest.approx((15, 22))
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx((15, 22))
    cyclic = replace(
        rotated,
        leader_target_mm=(30, 30),
        leader_annotation_attachment=AnnotationAttachment("frame", dependent.frame_id, (0, 0)),
    )
    with pytest.raises(ValidationError, match="循环"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"update_frames": [cyclic.to_mapping()]}, "local"
        )
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx((12, 10))
    path = tmp_path / "annotation-reference.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)


def test_mixed_move_annotation_and_frame_keeps_attachment() -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", source.frame_id, (0, 0)),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [source.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    app.move_tolerance_selection(
        services, loaded, (), (source.frame_id,), (datum.datum_id,), (), (5, 3), session_identity=0
    )
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.position_mm == (25, 23) and moved.target_mm == (5, 3)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_imported_annotation_attachment_remaps_colliding_frame_identity() -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    identity = uuid4().hex
    existing = FeatureControlFrame(identity, (ToleranceRow("position", 0.1, 2),), (100, 100))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [existing.to_mapping()]}, "local")
    imported = FeatureControlFrame(identity, existing.rows, (0, 0))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", identity, (0, 0)),
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
        session_identity=0,
        imported_tolerance_frames=(imported,),
        imported_datums=(datum,),
    )
    copied_frame = services.kernel.drawing_tolerance_frames[1]
    copied_datum = services.kernel.drawing_datum_identifiers[0]
    assert copied_frame.frame_id != identity
    assert copied_datum.annotation_attachment is not None
    assert copied_datum.annotation_attachment.object_id == copied_frame.frame_id


def test_mixed_move_preserves_unselected_annotation_target() -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment
    from mycad.core.sketch import LineEntity

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (20, 10))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (30, 20),
        (20, 10),
        annotation_attachment=AnnotationAttachment("frame", source.frame_id, (0, 0)),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [source.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    app.move_tolerance_selection(
        services, loaded, (line.entity_id,), (), (datum.datum_id,), (), (5, 3), session_identity=0
    )
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.position_mm == (35, 23) and moved.target_mm == (20, 10)


@pytest.mark.parametrize("rotated_ordinate", [False, True])
def test_mixed_move_reference_dimension_and_attached_datum(rotated_ordinate: bool) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import AnnotationAttachment

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dimension = (
        DetachedDimension(uuid4().hex, "ordinate_y", (0, 0), (4, 3), (0, 5), 90, -4)
        if rotated_ordinate
        else DetachedDimension(uuid4().hex, "aligned", (0, 0), (10, 0), (0, 5), 0, 10)
    )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local"
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 5),
        annotation_attachment=AnnotationAttachment(
            "reference_dimension", dimension.dimension_id, (0, 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    app.move_tolerance_selection(
        services,
        loaded,
        (),
        (),
        (datum.datum_id,),
        (dimension.dimension_id,),
        (5, 3),
        session_identity=0,
    )
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.position_mm == (25, 23) and moved.target_mm == (5, 8)
    moved_dimension = services.kernel.drawing_reference_dimensions[0]
    assert moved_dimension.angle_deg == dimension.angle_deg
    assert moved_dimension.nominal == dimension.nominal
    assert moved_dimension.first_mm == (5, 3)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_reference_dimensions == (dimension,)


def test_deleting_attached_frame_is_rejected_until_detached() -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (10, 10))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (10, 10),
        annotation_attachment=AnnotationAttachment("frame", source.frame_id, (0, 0)),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [source.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute("drawing.tolerance.batch", {"remove_frames": [source.frame_id]}, "local")
    assert services.kernel.drawing_tolerance_frames == (source,)
    detached = replace(datum, annotation_attachment=None)
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"remove_frames": [source.frame_id], "update_datums": [detached.to_mapping()]},
        "local",
    )
    assert services.kernel.drawing_datum_identifiers == (detached,)


def test_annotation_follows_reference_dimension_and_protects_deletion() -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import AnnotationAttachment

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    dim = DetachedDimension(uuid4().hex, "aligned", (0, 0), (10, 0), (0, 5), 0, 10)
    loaded.bus.execute("drawing.reference_dimensions.batch", {"add": [dim.to_mapping()]}, "local")
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (2, 5),
        annotation_attachment=AnnotationAttachment("reference_dimension", dim.dimension_id, (2, 0)),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    moved = replace(dim, location_mm=(5, 8))
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"update": [moved.to_mapping()]}, "local"
    )
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (7, 8)
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.reference_dimensions.batch", {"remove": [dim.dimension_id]}, "local"
        )
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_attached_sketch_dimension_cannot_be_deleted_silently() -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=10,
        unit="mm",
        position_mm=(0, 5),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 5),
        annotation_attachment=AnnotationAttachment(
            "sketch_dimension", dim.constraint_id, (0, 0), sketch.sketch_id
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    state = replace(sketch, constraints=()).to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
            version=55,
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_annotation_on_sketch_dimension_text_follows_text_move() -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=10,
        unit="mm",
        position_mm=(0, 5),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dim,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    ref = AnnotationAttachment(
        "sketch_dimension", dim.constraint_id, (1, 0), sketch.sketch_id, anchor="text"
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (1, 5), annotation_attachment=ref)
    with pytest.raises(ValidationError, match="版本 15"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=14
        )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    updated = replace(dim, text_position_mm=(4, 8))
    preview = services.kernel.preview_sketch_constraint_update(sketch, updated)
    assert preview.status == "success"
    loaded.bus.execute(
        "sketch.constraint.update",
        preview.command_params(sketch, updated, local_frame=True),
        "local",
        version=7,
    )
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx((5, 8))
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_ellipse_datum_follows_sketch_revision(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import EllipseEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    ellipse = EllipseEntity(uuid4().hex, (0, 0), 10, 5)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (ellipse,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(ellipse.entity_id, "geometry"),
        0.25,
        curve_kind="ellipse",
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 20), ellipse.point_at(0.25), attachment=attachment
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(sketch, entities=(replace(ellipse, minor_radius_mm=8),))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=55,
    )
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx((0, 8))
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx(datum.target_mm)
    path = tmp_path / "ellipse-datum.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)


def test_ellipse_datum_normal_tracks_radius_change() -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_normal
    from mycad.core.sketch import EllipseEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    ellipse = EllipseEntity(uuid4().hex, (0, 0), 10, 5, rotation_deg=20)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (ellipse,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(ellipse.entity_id, "geometry"),
        0.125,
        curve_kind="ellipse",
    )
    target = ellipse.point_at(0.125)
    normal = resolve_attachment_normal(attachment, sketch, target)
    assert normal is not None
    vertex = (target[0] + 3 * normal[0], target[1] + 3 * normal[1])
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        target,
        attachment=attachment,
        leader_offsets=((vertex[0] - 20, vertex[1] - 20),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(sketch, entities=(replace(ellipse, minor_radius_mm=8),))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=55,
    )
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_normal = resolve_attachment_normal(attachment, changed, updated.target_mm)
    assert updated_normal is not None
    current_vertex = (
        updated.position_mm[0] + updated.leader_offsets[-1][0],
        updated.position_mm[1] + updated.leader_offsets[-1][1],
    )
    direction = (current_vertex[0] - updated.target_mm[0], current_vertex[1] - updated.target_mm[1])
    assert math.hypot(*direction) == pytest.approx(3)
    assert direction[0] * updated_normal[1] - direction[1] * updated_normal[0] == pytest.approx(
        0, abs=1e-9
    )


@pytest.mark.parametrize("kind", ["circle", "arc"])
def test_curved_datum_normal_follows_revision_and_history(tmp_path: Path, kind: str) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import (
        resolve_attachment_local,
        resolve_attachment_normal,
    )
    from mycad.core.sketch import ArcEntity, CircleEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entity = (
        CircleEntity(uuid4().hex, (0, 0), 10)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 0), 10, 0, 90)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entity.entity_id, "geometry"), 0.25
    )
    target = resolve_attachment_local(attachment, {entity.entity_id: entity})
    assert target is not None
    normal = resolve_attachment_normal(attachment, sketch, target)
    assert normal is not None
    position = (30.0, 30.0)
    vertex = (target[0] + 3 * normal[0], target[1] + 3 * normal[1])
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        position,
        target,
        attachment=attachment,
        leader_offsets=((vertex[0] - position[0], vertex[1] - position[1]),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed_entity = (
        replace(entity, center_mm=(3, 4), radius_mm=15)
        if isinstance(entity, CircleEntity)
        else replace(entity, center_mm=(3, 4), radius_mm=15, start_angle_deg=45)
    )
    changed_sketch = replace(sketch, entities=(changed_entity,))
    state = changed_sketch.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    updated = services.kernel.drawing_datum_identifiers[0]
    new_normal = resolve_attachment_normal(attachment, changed_sketch, updated.target_mm)
    assert new_normal is not None
    vector = (
        updated.position_mm[0] + updated.leader_offsets[-1][0] - updated.target_mm[0],
        updated.position_mm[1] + updated.leader_offsets[-1][1] - updated.target_mm[1],
    )
    assert math.hypot(*vector) == pytest.approx(3)
    assert vector[0] * new_normal[1] - vector[1] * new_normal[0] == pytest.approx(0, abs=1e-9)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated,)
    path = tmp_path / "curved-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)


def test_mixed_annotation_delete_rolls_back_when_reference_dimension_missing() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        app.delete_tolerance_selection(
            services, loaded, (frame.frame_id,), (), (uuid4().hex,), session_identity=0
        )
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert loaded.document.command_count == count


def test_mixed_annotation_delete_rolls_back_when_image_missing() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        app.delete_tolerance_selection(
            services,
            loaded,
            (frame.frame_id,),
            (),
            (),
            session_identity=0,
            raster_ids=(uuid4().hex,),
        )
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert loaded.document.command_count == count


def test_mixed_annotation_delete_preserves_reference_when_datum_is_still_used() -> None:
    from mycad.core.detached_dimension import DetachedDimension

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (4, 5),
    )
    dimension = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [dimension.to_mapping()]}, "local"
    )
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        app.delete_tolerance_selection(
            services, loaded, (), (datum.datum_id,), (dimension.dimension_id,), session_identity=0
        )
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_reference_dimensions == (dimension,)
    assert loaded.document.command_count == count


@pytest.mark.parametrize(
    ("fixture", "position", "associated"),
    [
        ("cadcraft-0.20.1-multiline.dxf", (10, 20), False),
        ("cadcraft-moved-frame.dxf", (5, 23), True),
    ],
)
def test_cadcraft_multiline_frame_survives_history_and_save(
    tmp_path: Path, fixture: str, position: tuple[int, int], associated: bool
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    source = Path(__file__).parents[1] / "fixtures/dxf" / fixture
    imported = read_sketch_dxf(source, unit_override="mm")
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    app.commit_new_sketch(
        services,
        loaded,
        imported.sketch,
        session_identity=0,
        imported_text_styles=imported.text_styles,
        imported_tolerance_frames=imported.tolerance_frames,
        imported_datums=imported.datum_identifiers,
    )
    frames = services.kernel.drawing_tolerance_frames
    datums = services.kernel.drawing_datum_identifiers
    frame = next(item for item in frames if len(item.rows) == 2)
    assert frame.position_mm == position
    assert [row.value for row in frame.rows] == [0.12, 0.08]
    assert [ref.label for ref in frame.rows[0].datums] == ["A", "B", "C"]
    assert all((ref.datum_id is not None) == associated for ref in frame.rows[0].datums)
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_datum_identifiers

    loaded.bus.redo_operation()
    assert services.kernel.drawing_tolerance_frames == frames
    assert services.kernel.drawing_datum_identifiers == datums
    path = tmp_path / "external-frames.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == frames
    assert reopened.kernel.drawing_datum_identifiers == datums


@pytest.mark.parametrize(
    ("array_uses_polyline", "same_sketch", "rotated"),
    [(False, False, False), (True, False, False), (False, True, False), (True, False, True)],
)
def test_reorder_handles_unrelated_array_without_weakening_related_protection(
    array_uses_polyline: bool, same_sketch: bool, rotated: bool
) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    line = LineEntity(uuid4().hex, (30, 0), (40, 0))
    drawing = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (polyline, line) if same_sketch else (polyline,)
    )
    unrelated = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    source = polyline if array_uses_polyline else line
    source_sketch = drawing if array_uses_polyline or same_sketch else unrelated
    target = (
        PolylineEntity(
            uuid4().hex,
            ((0, 20), (0, 30), (-10, 30)) if rotated else ((0, 20), (10, 20), (10, 30)),
        )
        if array_uses_polyline
        else LineEntity(uuid4().hex, (30, 20), (40, 20))
    )
    target_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    for sketch in (drawing, target_sketch) if same_sketch else (drawing, unrelated, target_sketch):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source_ref = ArrayEntityRef(source_sketch.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(target_sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        source_sketch.frame,
        2,
        1,
        20,
        0,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 1, 0, rotation_deg=90 if rotated else 0),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        drawing.sketch_id, SketchGeometryReference(polyline.entity_id, "segment", 0), 0.25, 2
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 5), (2.5, 0), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = next(item for item in services.kernel.sketches if item.sketch_id == drawing.sketch_id)
    reverse = replace(polyline, points_mm=tuple(reversed(polyline.points_mm)))
    state = replace(
        current,
        entities=tuple(
            reverse if item.entity_id == polyline.entity_id else item for item in current.entities
        ),
    ).to_state_mapping()
    mapping = PolylineTopologyMap(polyline.entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    if rotated:
        count = loaded.document.command_count
        with pytest.raises(ValidationError):
            loaded.bus.execute("drawing.sketch.revise", params, "local", version=57)
        assert loaded.document.command_count == count
        assert services.kernel.drawing_datum_identifiers == (datum,)
    else:
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=57)
        updated = services.kernel.drawing_datum_identifiers[0]
        assert updated.attachment is not None and updated.attachment.reference.index == 1
        assert updated.target_mm == pytest.approx((2.5, 0))
        assert services.kernel.associative_arrays == (array,)


def test_dxf_duplicate_datum_id_is_imported_as_unresolved_without_losing_other_objects(
    tmp_path: Path,
) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    shared_id = uuid4().hex
    first = DatumIdentifier(shared_id, "A", (0, 0), (0, -5))
    second = DatumIdentifier(shared_id, "B", (10, 0), (10, -5))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.05, 2, datums=(DatumReference("A", shared_id),)),),
        (10, 20),
    )
    path = tmp_path / "duplicate-datum.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(first, second))
    imported = read_sketch_dxf(path)
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    app.commit_new_sketch(
        services,
        loaded,
        imported.sketch,
        session_identity=0,
        imported_tolerance_frames=imported.tolerance_frames,
        imported_datums=imported.datum_identifiers,
    )
    assert {item.label for item in services.kernel.drawing_datum_identifiers} == {"A", "B"}
    assert services.kernel.drawing_tolerance_frames[0].rows[0].datums == (DatumReference("A"),)
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_datum_identifiers
    assert not services.kernel.drawing_tolerance_frames
    loaded.bus.redo_operation()
    assert len(services.kernel.drawing_datum_identifiers) == 2
    assert services.kernel.drawing_tolerance_frames[0].rows[0].datums == (DatumReference("A"),)


def test_dxf_duplicate_frames_import_undo_redo_and_reopen(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.05, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (10, 20),
    )
    dxf_path = tmp_path / "duplicate-frames.dxf"
    write_sketches_dxf(
        (),
        dxf_path,
        tolerance_frames=(frame, replace(frame, position_mm=(20, 30))),
        datum_identifiers=(datum,),
    )
    imported = read_sketch_dxf(dxf_path)
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    app.commit_new_sketch(
        services,
        loaded,
        imported.sketch,
        session_identity=0,
        imported_tolerance_frames=imported.tolerance_frames,
        imported_datums=imported.datum_identifiers,
    )
    expected_frames = services.kernel.drawing_tolerance_frames
    assert len(expected_frames) == 2
    assert all(item.rows[0].datums[0].datum_id == datum.datum_id for item in expected_frames)
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_tolerance_frames
    loaded.bus.redo_operation()
    assert services.kernel.drawing_tolerance_frames == expected_frames
    path = tmp_path / "duplicate-frames.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.drawing_tolerance_frames == expected_frames
    assert reopened_services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("collision", ["frame_datum", "frame_reference", "datum_reference"])
def test_new_annotations_reject_identity_collision_across_kinds(collision: str) -> None:
    from mycad.core.detached_dimension import DetachedDimension

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    identity = uuid4().hex
    frame = FeatureControlFrame(identity, (ToleranceRow("flatness", 0.1, 2),), (1, 2))
    datum = DatumIdentifier(identity, "A", (2, 3), (2, 0))
    reference = DetachedDimension(identity, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    if collision == "frame_datum":
        with pytest.raises(ValidationError, match="身份"):
            loaded.bus.execute(
                "drawing.tolerance.batch",
                {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
                "local",
            )
        assert loaded.document.command_count == 0
    else:
        params = (
            {"add_frames": [frame.to_mapping()]}
            if collision == "frame_reference"
            else {"add_datums": [datum.to_mapping()]}
        )
        loaded.bus.execute("drawing.tolerance.batch", params, "local")
        with pytest.raises(ValidationError, match="身份"):
            loaded.bus.execute(
                "drawing.reference_dimensions.batch", {"add": [reference.to_mapping()]}, "local"
            )
        assert loaded.document.command_count == 1


@pytest.mark.parametrize("kind", ["frame", "datum"])
def test_new_tolerance_cannot_reuse_existing_reference_identity(kind: str) -> None:
    from mycad.core.detached_dimension import DetachedDimension

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    identity = uuid4().hex
    reference = DetachedDimension(identity, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [reference.to_mapping()]}, "local"
    )
    frame = FeatureControlFrame(identity, (ToleranceRow("flatness", 0.1, 2),), (1, 2))
    datum = DatumIdentifier(identity, "A", (2, 3), (2, 0))
    params = (
        {"add_frames": [frame.to_mapping()]}
        if kind == "frame"
        else {"add_datums": [datum.to_mapping()]}
    )
    with pytest.raises(ValidationError, match="身份"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local")
    assert services.kernel.drawing_reference_dimensions == (reference,)
    assert loaded.document.command_count == 1


def test_legacy_cross_kind_identity_collision_replays_and_can_be_repaired(tmp_path: Path) -> None:
    from mycad.core.detached_dimension import DetachedDimension

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    identity = uuid4().hex
    frame = FeatureControlFrame(identity, (ToleranceRow("flatness", 0.1, 2),), (1, 2))
    datum = DatumIdentifier(identity, "A", (2, 3), (2, 0))
    reference = DetachedDimension(identity, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
        version=6,
    )
    loaded.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [reference.to_mapping()]}, "local", version=5
    )
    path = tmp_path / "legacy-identities.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.drawing_tolerance_frames == (frame,)
    assert reopened_services.kernel.drawing_datum_identifiers == (datum,)
    assert reopened_services.kernel.drawing_reference_dimensions == (reference,)
    reopened.bus.execute("drawing.tolerance.batch", {"remove_frames": [identity]}, "local")
    assert not reopened_services.kernel.drawing_tolerance_frames
    reopened.bus.undo_operation()
    assert reopened_services.kernel.drawing_tolerance_frames == (frame,)


def test_import_remaps_cross_kind_annotation_id_collision() -> None:
    from mycad.core.detached_dimension import DetachedDimension

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    identity = uuid4().hex
    datum = DatumIdentifier(identity, "A", (0, 0), (0, -5))
    frame = FeatureControlFrame(
        identity,
        (ToleranceRow("position", 0.05, 2, datums=(DatumReference("A", identity),)),),
        (10, 20),
    )
    dimension = DetachedDimension(identity, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
        session_identity=0,
        imported_tolerance_frames=(frame,),
        imported_datums=(datum,),
        imported_reference_dimensions=(dimension,),
    )
    restored_frame = services.kernel.drawing_tolerance_frames[0]
    restored_datum = services.kernel.drawing_datum_identifiers[0]
    restored_dimension = services.kernel.drawing_reference_dimensions[0]
    assert (
        len({restored_frame.frame_id, restored_datum.datum_id, restored_dimension.dimension_id})
        == 3
    )
    assert restored_frame.rows[0].datums == (DatumReference("A", restored_datum.datum_id),)
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_datum_identifiers
    assert not services.kernel.drawing_reference_dimensions


def test_geometric_annotations_atomic_history_and_reopen(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, True, "M", (DatumReference("A", datum.datum_id),)),),
        (4, 5),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    report = DXF_PROVIDER.write(services.kernel, tmp_path / "annotations.dxf")
    assert isinstance(report, DxfExchangeReport)
    assert report.entity_count == 2
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.tolerance.batch", {"remove_datums": [datum.datum_id]}, "local")
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert loaded.document.command_count == 1
    renamed = replace(datum, label="C")
    loaded.bus.execute(
        "drawing.tolerance.batch", {"update_datums": [renamed.to_mapping()]}, "local"
    )
    assert services.kernel.drawing_tolerance_frames[0].rows[0].datums[0].label == "C"
    loaded.bus.undo()
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo()
    path = tmp_path / "geometric.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (renamed,)
    assert reopened.kernel.drawing_tolerance_frames[0].rows[0].datums[0].label == "C"


def test_frame_text_style_reference_is_versioned_and_protected(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle(style_id="iso-font", name="公差字体", height_mm=4.5)
    styles = TextStyleTable((TextStyle(), style))
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local")
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0), text_style_id=style.style_id
    )
    with pytest.raises(ValidationError, match="版本"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local", version=4
        )
    missing = replace(frame, text_style_id="missing")
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_frames": [missing.to_mapping()]}, "local", version=5
        )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local", version=5
    )
    with pytest.raises(ValidationError, match="样式"):
        loaded.bus.execute("drawing.text_styles.set", TextStyleTable().to_mapping(), "local")
    path = tmp_path / "frame-style.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    document = app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (frame,)
    document.bus.undo()
    assert not reopened.kernel.drawing_tolerance_frames
    document.bus.redo()
    assert reopened.kernel.drawing_tolerance_frames == (frame,)


def test_datum_text_style_reference_is_versioned_and_protected(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle(style_id="datum-font", name="基准字体", height_mm=5)
    styles = TextStyleTable((TextStyle(), style))
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local")
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5), text_style_id=style.style_id)
    with pytest.raises(ValidationError, match="版本"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=5
        )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch",
            {"add_datums": [replace(datum, text_style_id="missing").to_mapping()]},
            "local",
            version=6,
        )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=6
    )
    with pytest.raises(ValidationError, match="样式"):
        loaded.bus.execute("drawing.text_styles.set", TextStyleTable().to_mapping(), "local")
    path = tmp_path / "datum-style.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    document = app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)
    document.bus.undo()
    assert not reopened.kernel.drawing_datum_identifiers
    document.bus.redo()
    assert reopened.kernel.drawing_datum_identifiers == (datum,)


def test_dxf_frame_style_import_reconciles_target_conflict(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    source_style = TextStyle("frame-font", "检验字体", height_mm=7, width_factor=1.25)
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0), text_style_id="frame-font"
    )
    path = tmp_path / "frame-style.dxf"
    write_sketches_dxf(
        (),
        path,
        tolerance_frames=(frame,),
        text_styles=TextStyleTable((source_style,), "frame-font"),
    )
    imported = read_sketch_dxf(path)
    incoming_id = imported.tolerance_frames[0].text_style_id
    assert incoming_id is not None and imported.text_styles is not None
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    conflicting = TextStyle(incoming_id, "目标字体", height_mm=2)
    target = TextStyleTable((TextStyle(), conflicting))
    loaded.bus.execute("drawing.text_styles.set", target.to_mapping(), "local")
    app.commit_new_sketch(
        services,
        loaded,
        imported.sketch,
        session_identity=0,
        imported_text_styles=imported.text_styles,
        imported_tolerance_frames=imported.tolerance_frames,
    )
    installed = services.kernel.drawing_tolerance_frames[0].text_style_id
    assert installed is not None and installed != incoming_id
    assert services.kernel.drawing_text_styles.get(installed).height_mm == 7
    assert services.kernel.drawing_text_styles.get(incoming_id) == conflicting
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_tolerance_frames
    assert services.kernel.drawing_text_styles == target
    loaded.bus.redo_operation()
    assert services.kernel.drawing_tolerance_frames[0].text_style_id == installed


def test_dxf_datum_style_import_reconciles_target_conflict(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    source_style = TextStyle("datum-font", "基准字体", "DejaVu Sans", height_mm=7, width_factor=1.5)
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5), text_style_id="datum-font")
    path = tmp_path / "datum-style.dxf"
    write_sketches_dxf(
        (),
        path,
        datum_identifiers=(datum,),
        text_styles=TextStyleTable((source_style,), "datum-font"),
    )
    imported = read_sketch_dxf(path)
    incoming_id = imported.datum_identifiers[0].text_style_id
    assert incoming_id is not None and imported.text_styles is not None
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    conflicting = TextStyle(incoming_id, "目标字体", height_mm=2)
    target = TextStyleTable((TextStyle(), conflicting))
    loaded.bus.execute("drawing.text_styles.set", target.to_mapping(), "local")
    app.commit_new_sketch(
        services,
        loaded,
        imported.sketch,
        session_identity=0,
        imported_text_styles=imported.text_styles,
        imported_datums=imported.datum_identifiers,
    )
    installed = services.kernel.drawing_datum_identifiers[0].text_style_id
    assert installed is not None and installed != incoming_id
    assert services.kernel.drawing_text_styles.get(installed).height_mm == 7
    assert services.kernel.drawing_text_styles.get(incoming_id) == conflicting
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_datum_identifiers
    assert services.kernel.drawing_text_styles == target
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers[0].text_style_id == installed


def test_dxf_import_unifies_shared_frame_and_datum_font(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    font = TextStyle("shared", "检验字体", "DejaVu Sans", height_mm=7, width_factor=1.5)
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5), text_style_id="shared")
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (10, 10),
        text_style_id="shared",
    )
    path = tmp_path / "shared-style.dxf"
    write_sketches_dxf(
        (),
        path,
        tolerance_frames=(frame,),
        datum_identifiers=(datum,),
        text_styles=TextStyleTable((font,), "shared"),
    )
    imported = read_sketch_dxf(path)
    assert imported.text_styles is not None
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    app.commit_new_sketch(
        services,
        loaded,
        imported.sketch,
        session_identity=0,
        imported_text_styles=imported.text_styles,
        imported_tolerance_frames=imported.tolerance_frames,
        imported_datums=imported.datum_identifiers,
    )
    saved_frame = services.kernel.drawing_tolerance_frames[0]
    saved_datum = services.kernel.drawing_datum_identifiers[0]
    assert saved_frame.text_style_id == saved_datum.text_style_id
    assert saved_frame.text_style_id is not None
    assert services.kernel.drawing_text_styles.get(saved_frame.text_style_id).height_mm == 7
    assert saved_frame.rows[0].datums[0].datum_id == saved_datum.datum_id
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_datum_identifiers
    loaded.bus.redo_operation()
    assert (
        services.kernel.drawing_tolerance_frames[0].rows[0].datums[0].datum_id
        == saved_datum.datum_id
    )


def test_renaming_datum_cannot_modify_frame_on_locked_layer() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("公差"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    datum = DatumIdentifier(uuid4().hex, "A", (0, 1), (0, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (1, 1),
        layer_name="公差",
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "公差" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch",
            {"update_datums": [replace(datum, label="B").to_mapping()]},
            "local",
        )
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_datum_names_are_unique_case_insensitively_and_batch_is_atomic() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = DatumIdentifier(uuid4().hex, "A", (0, 1), (0, 0))
    duplicate = DatumIdentifier(uuid4().hex, "a", (2, 1), (2, 0))
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch",
            {"add_datums": [first.to_mapping(), duplicate.to_mapping()]},
            "local",
        )
    assert not services.kernel.drawing_datum_identifiers
    assert not loaded.document.commands


def test_frame_only_import_is_atomic_and_replayable() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (4, 5))
    empty = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    app.commit_new_sketch(
        services, loaded, empty, session_identity=1, imported_tolerance_frames=(frame,)
    )
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.undo()
    assert services.kernel.drawing_tolerance_frames == ()
    loaded.bus.redo()
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_imported_frames_remap_duplicate_ids_and_detach_foreign_datums() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (0, 1), (0, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (4, 5),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    empty = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    app.commit_new_sketch(
        services, loaded, empty, session_identity=1, imported_tolerance_frames=(frame,)
    )
    first, second = services.kernel.drawing_tolerance_frames
    assert first == frame
    assert second.frame_id != frame.frame_id
    assert second.rows[0].datums == (DatumReference("A"),)


def test_imported_datum_and_frame_retain_reference_in_one_transaction() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (3, 4),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    app.commit_new_sketch(
        services,
        loaded,
        sketch,
        session_identity=1,
        imported_tolerance_frames=(frame,),
        imported_datums=(datum,),
    )
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.undo()
    assert not services.kernel.drawing_datum_identifiers
    assert not services.kernel.drawing_tolerance_frames


def test_import_datum_id_collision_is_remapped_for_linked_frame() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    shared_id = uuid4().hex
    existing = DatumIdentifier(shared_id, "A", (0, 2), (0, 0))
    foreign = DatumIdentifier(shared_id, "B", (1, 2), (1, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("B", shared_id),)),),
        (5, 5),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [existing.to_mapping()]}, "local")
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
        session_identity=1,
        imported_tolerance_frames=(frame,),
        imported_datums=(foreign,),
    )
    added = services.kernel.drawing_datum_identifiers[1]
    assert added.datum_id != shared_id
    assert services.kernel.drawing_tolerance_frames[0].rows[0].datums[0].datum_id == added.datum_id


def test_import_duplicate_datum_name_rejects_the_whole_transaction() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    existing = DatumIdentifier(uuid4().hex, "A", (0, 2), (0, 0))
    foreign = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", foreign.datum_id),)),),
        (5, 5),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [existing.to_mapping()]}, "local")
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="名称不能重复"):
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
            session_identity=1,
            imported_tolerance_frames=(frame,),
            imported_datums=(foreign,),
        )
    assert loaded.document.command_count == count
    assert services.kernel.drawing_datum_identifiers == (existing,)
    assert not services.kernel.drawing_tolerance_frames


def test_attached_datum_follows_geometry_and_preserves_last_position_on_deletion(
    tmp_path: Path,
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 2), (5, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (1, 2),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")

    def revise(before: Sketch, after: Sketch) -> None:
        state = after.to_state_mapping()
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": before.sketch_id,
                        "base_state_sha256": before.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )

    moved = replace(sketch, entities=(replace(line, start_mm=(3, 6)),))
    revise(sketch, moved)
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (3, 6)
    revise(moved, replace(moved, entities=()))
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (3, 6)
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)
    loaded.bus.undo()
    assert services.kernel.datum_attachment_resolved(datum.datum_id)
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (3, 6)
    loaded.bus.redo()
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)
    path = tmp_path / "attached.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers[0].target_mm == (3, 6)
    assert not reopened.kernel.datum_attachment_resolved(datum.datum_id)


def test_new_datum_cannot_attach_to_missing_or_inconsistent_geometry() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 2), (5, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (99, 99),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    missing = replace(
        datum,
        attachment=DatumAttachment(sketch.sketch_id, SketchGeometryReference(uuid4().hex, "start")),
    )
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [missing.to_mapping()]}, "local"
        )


def test_attached_datum_cannot_be_updated_to_a_false_target() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 2), (5, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (1, 2),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.tolerance.batch",
            {"update_datums": [replace(datum, target_mm=(3, 4)).to_mapping()]},
            "local",
        )


def test_datum_attachment_uses_new_command_version_without_changing_version_one() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 2), (5, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (1, 2),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=1
        )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=2
    )
    assert loaded.document.commands[-1].version == 2
    loaded.bus.undo()
    loaded.bus.redo()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_normal_datum_leader_follows_attached_line_revision() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (2.5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), parameter=0.25
        ),
        leader_offsets=((-7.5, -7),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    moved = replace(sketch, entities=(replace(line, end_mm=(20, 0)),))
    state = moved.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    changed = services.kernel.drawing_datum_identifiers[0]
    assert changed.target_mm == (5, 0)
    assert changed.leader_offsets[-1] == pytest.approx((-5, -7))
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_frame_leader_follows_attached_geometry_and_replays(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), parameter=0.25
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(2.5, 0),
        leader_anchor_offset=(0, -3),
        leader_attachment=attachment,
    )
    assert FeatureControlFrame.from_mapping(frame.to_mapping()) == frame
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local", version=9
        )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    moved = replace(sketch, entities=(replace(line, end_mm=(20, 0)),))
    state = moved.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    assert services.kernel.drawing_tolerance_frames[0].leader_target_mm == (5, 0)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_tolerance_frames == (frame,)
    path = tmp_path / "attached-frame.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (frame,)


def test_normal_datum_does_not_drift_on_unrelated_annotation() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-14, -7),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    saved = services.kernel.drawing_datum_identifiers[0]
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    assert services.kernel.drawing_datum_identifiers[0] == saved


@pytest.mark.parametrize("version", [55, 56])
def test_normal_leader_large_rotation_versioned_side_choice(tmp_path: Path, version: int) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-10, -6),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(sketch, entities=(replace(line, end_mm=(-5, 5 * math.sqrt(3))),))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=version,
    )
    updated = services.kernel.drawing_datum_identifiers[0]
    offset = updated.leader_offsets[-1]
    expected = (2 * math.sqrt(3), 2) if version == 55 else (-2 * math.sqrt(3), -2)
    assert (
        updated.position_mm[0] + offset[0],
        updated.position_mm[1] + offset[1],
    ) == pytest.approx(expected)
    path = tmp_path / "legacy-large-normal-rotation.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("surface", [False, True])
def test_normal_side_follows_large_rotation_for_annotations(owner: str, surface: bool) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    indication = (
        SurfaceIndication((-1, 8), (1, 8), 0.5, ((0, 4),), auto_normal=True) if surface else None
    )
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (10, 10),
            (0, 0),
            attachment=attachment,
            leader_offsets=() if surface else ((-10, -6),),
            leader_auto_normal=not surface,
            surface_indication=indication,
        )
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (10, 10),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            leader_offsets=() if surface else ((-10, -6),),
            leader_auto_normal=not surface,
            surface_indication=indication,
        )
        params = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params, "local")
    changed = replace(sketch, entities=(replace(line, end_mm=(-5, 5 * math.sqrt(3))),))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=56,
    )
    result = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    if surface:
        assert result.surface_indication is not None
        vector = result.surface_indication.leader_offsets_mm[0]
    else:
        offset = result.leader_offsets[-1]
        vector = (result.position_mm[0] + offset[0], result.position_mm[1] + offset[1])
    assert vector == pytest.approx((-2 * math.sqrt(3), -2))
    loaded.bus.undo_operation()
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == item
    loaded.bus.redo_operation()
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == result


@pytest.mark.parametrize("curve_kind", ["arc", "spline"])
@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("surface", [False, True])
def test_normal_side_follows_large_curve_rotation(
    tmp_path: Path, curve_kind: str, owner: str, surface: bool
) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_normal
    from mycad.core.sketch import ArcEntity, SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    if curve_kind == "arc":
        entity = ArcEntity(uuid4().hex, (0, 0), 10, 0, 90)
        rotated = replace(entity, start_angle_deg=120)
        target = (5 * math.sqrt(2), 5 * math.sqrt(2))
    else:
        entity = SplineEntity(uuid4().hex, ((0, 0), (4, 0), (8, 0), (12, 0)))

        def rotate(p: tuple[float, float]) -> tuple[float, float]:
            return (-p[0] / 2 - p[1] * math.sqrt(3) / 2, p[0] * math.sqrt(3) / 2 - p[1] / 2)

        rotated = replace(
            entity, control_points_mm=tuple(rotate(p) for p in entity.control_points_mm)
        )
        target = entity.point_at(0.5)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(entity.entity_id, "geometry"),
        0.5,
        curve_kind="spline" if curve_kind == "spline" else None,
        control_count=4 if curve_kind == "spline" else None,
    )
    normal = resolve_attachment_normal(attachment, sketch, target, enable_spline=True)
    assert normal is not None
    vertex = (target[0] + 4 * normal[0], target[1] + 4 * normal[1])
    offset = (vertex[0] - 30, vertex[1] - 30)
    indication = (
        SurfaceIndication(
            (6 * normal[0] - 1, 6 * normal[1]),
            (6 * normal[0] + 1, 6 * normal[1]),
            0.5,
            ((4 * normal[0], 4 * normal[1]),),
            auto_normal=True,
        )
        if surface
        else None
    )
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (30, 30),
            target,
            attachment=attachment,
            leader_offsets=() if surface else (offset,),
            leader_auto_normal=not surface,
            spline_normal_enabled=curve_kind == "spline",
            surface_indication=indication,
        )
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (30, 30),
            leader_target_mm=target,
            leader_attachment=attachment,
            leader_offsets=() if surface else (offset,),
            leader_auto_normal=not surface,
            surface_indication=indication,
        )
        params = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params, "local")
    changed = replace(sketch, entities=(rotated,))
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=56,
    )
    result = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    new_target = (
        result.target_mm if isinstance(result, DatumIdentifier) else result.leader_target_mm
    )
    assert new_target is not None
    if surface:
        assert result.surface_indication is not None
        vector = result.surface_indication.leader_offsets_mm[0]
    else:
        new_offset = result.leader_offsets[-1]
        vector = (
            result.position_mm[0] + new_offset[0] - new_target[0],
            result.position_mm[1] + new_offset[1] - new_target[1],
        )
    expected = (
        -normal[0] / 2 - normal[1] * math.sqrt(3) / 2,
        normal[0] * math.sqrt(3) / 2 - normal[1] / 2,
    )
    assert vector == pytest.approx((4 * expected[0], 4 * expected[1]))
    path = tmp_path / f"{curve_kind}-{owner}.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert (
        reopened.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames[0]
    ) == result


def test_mixed_draft_move_uses_normal_side_revision(tmp_path: Path) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import rotate_entities

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    draft_line = LineEntity(uuid4().hex, (20, 0), (30, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (draft_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        attachment=DatumAttachment(
            saved.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-10, -6),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    revisions: list[dict[str, object]] = []
    for sketch in (saved, draft):
        changed = replace(
            sketch,
            entities=rotate_entities(sketch.entities, (sketch.entities[0].entity_id,), (0, 0), 120),
        )
        state = changed.to_state_mapping()
        revisions.append(
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        )
    candidate = app.stage_mixed_drawing_move(services, loaded, draft, revisions, session_identity=0)
    assert candidate.preview(current_session_identity=0).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=0), current_session_identity=0
    )
    revision = next(
        command for command in loaded.document.commands if command.id == "drawing.sketch.revise"
    )
    assert revision.version == 56
    result = services.kernel.drawing_datum_identifiers[0]
    offset = result.leader_offsets[-1]
    assert (result.position_mm[0] + offset[0], result.position_mm[1] + offset[1]) == pytest.approx(
        (-2 * math.sqrt(3), -2)
    )
    path = tmp_path / "mixed-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (result,)


def test_cross_sketch_dimension_uses_normal_side_revision(tmp_path: Path) -> None:
    import math

    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_normal
    from mycad.core.sketch import CircleEntity, LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    attachment = DatumAttachment(
        first.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (5, 0),
        attachment=attachment,
        leader_offsets=((-15, -16),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 12, "mm"
    )
    app.commit_cross_sketch_dimension(
        services, loaded, first.sketch_id, dimension, session_identity=0
    )
    assert loaded.document.commands[-1].version == 56
    result = services.kernel.drawing_datum_identifiers[0]
    changed = next(
        sketch for sketch in services.kernel.sketches if sketch.sketch_id == first.sketch_id
    )
    normal = resolve_attachment_normal(attachment, changed, result.target_mm)
    assert normal is not None
    offset = result.leader_offsets[-1]
    vector = (
        result.position_mm[0] + offset[0] - result.target_mm[0],
        result.position_mm[1] + offset[1] - result.target_mm[1],
    )
    assert math.hypot(*vector) == pytest.approx(4)
    assert vector[0] * normal[0] + vector[1] * normal[1] == pytest.approx(4)
    path = tmp_path / "cross-dimension-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (result,)


@pytest.mark.parametrize("updating", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_single_sketch_constraint_solution_preserves_normal_side(
    updating: bool, legacy: bool, tmp_path: Path
) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    constraint = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 10, "mm"
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint,) if updating else ())
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-10, -6),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    result = (
        services.kernel.preview_sketch_constraint_update(sketch, constraint)
        if updating
        else services.kernel.preview_sketch_constraint(sketch, constraint)
    )
    assert result.status == "success"
    params = result.command_params(sketch, constraint, local_frame=True)
    rotated = replace(sketch, entities=(replace(line, end_mm=(-5, 5 * math.sqrt(3))),))
    params["solution_entities"] = rotated.to_state_mapping()["entities"]
    loaded.bus.execute(
        "sketch.constraint.update" if updating else "sketch.constraint.add",
        params,
        "local",
        version=(7 if updating else 9) if legacy else (8 if updating else 10),
    )
    changed = services.kernel.drawing_datum_identifiers[0]
    offset = changed.leader_offsets[-1]
    assert (
        changed.position_mm[0] + offset[0],
        changed.position_mm[1] + offset[1],
    ) == pytest.approx((2 * math.sqrt(3), 2) if legacy else (-2 * math.sqrt(3), -2))
    path = tmp_path / f"single-constraint-{updating}.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (changed,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_constraint_solution_rejects_attached_polyline_reordering(owner: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (20, 0), (30, 0))
    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, poly))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(poly.entity_id, "segment", 0), 0.5, 2
    )
    if owner == "datum":
        item = DatumIdentifier(uuid4().hex, "A", (20, 20), (5, 0), attachment=attachment)
        params_to_add = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (20, 20),
            leader_target_mm=(5, 0),
            leader_attachment=attachment,
        )
        params_to_add = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params_to_add, "local")
    constraint = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 10, "mm"
    )
    result = services.kernel.preview_sketch_constraint(sketch, constraint)
    assert result.status == "success"
    params = result.command_params(sketch, constraint, local_frame=True)
    reordered = replace(poly, points_mm=((0, 0), (10, 10), (10, 0)))
    params["solution_entities"] = replace(sketch, entities=(line, reordered)).to_state_mapping()[
        "entities"
    ]
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="重排"):
        loaded.bus.execute("sketch.constraint.add", params, "local", version=10)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,)
    assert (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    ) == (item,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_new_cross_tangency_rejects_attached_polyline_reordering(owner: str) -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        build_tangency_revisions,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import CircleEntity, LineEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (20, 0), (30, 0))
    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (25, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, poly))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        first.sketch_id, SketchGeometryReference(poly.entity_id, "segment", 0), 0.5, 2
    )
    if owner == "datum":
        item = DatumIdentifier(uuid4().hex, "A", (20, 20), (5, 0), attachment=attachment)
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (20, 20),
            leader_target_mm=(5, 0),
            leader_attachment=attachment,
        )
        params = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params, "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    changed = replace(first, entities=(line, replace(poly, points_mm=((0, 0), (10, 10), (10, 0)))))
    revisions = build_tangency_revisions((first, second), (changed, second))
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="重排"):
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": list(revisions)},
            "local",
            version=12,
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (first, second)
    assert not services.kernel.cross_sketch_tangencies
    assert (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    ) == (item,)


@pytest.mark.parametrize("version", [11, 12])
def test_tangency_versions_preserve_historical_normal_side(tmp_path: Path, version: int) -> None:
    import math

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        build_tangency_revisions,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import CircleEntity, LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import rotate_entities

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        attachment=DatumAttachment(
            first.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-10, -6),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    proposed = tuple(
        replace(
            sketch,
            entities=rotate_entities(sketch.entities, (sketch.entities[0].entity_id,), (0, 0), 120),
        )
        for sketch in (first, second)
    )
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add",
        {
            "relation": relation.to_mapping(),
            "revisions": list(build_tangency_revisions((first, second), proposed)),
        },
        "local",
        version=version,
    )
    result = services.kernel.drawing_datum_identifiers[0]
    offset = result.leader_offsets[-1]
    expected = (2 * math.sqrt(3), 2) if version == 11 else (-2 * math.sqrt(3), -2)
    assert (result.position_mm[0] + offset[0], result.position_mm[1] + offset[1]) == pytest.approx(
        expected
    )
    path = tmp_path / f"tangency-normal-{version}.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (result,)


@pytest.mark.parametrize("normal_enabled", [False, True])
def test_new_cross_sketch_tangency_preserves_existing_datum_normal(
    tmp_path: Path, normal_enabled: bool
) -> None:
    import math

    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_normal
    from mycad.core.sketch import CircleEntity, LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 3), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        first.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (5, 0),
        attachment=attachment,
        leader_offsets=((-15, -16),),
        leader_auto_normal=normal_enabled,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    assert loaded.document.commands[-1].id == "drawing.tangency.add"
    assert loaded.document.commands[-1].version == 12
    result = services.kernel.drawing_datum_identifiers[0]
    changed = next(
        sketch for sketch in services.kernel.sketches if sketch.sketch_id == first.sketch_id
    )
    normal = resolve_attachment_normal(attachment, changed, result.target_mm)
    assert normal is not None
    offset = result.leader_offsets[-1]
    vector = (
        result.position_mm[0] + offset[0] - result.target_mm[0],
        result.position_mm[1] + offset[1] - result.target_mm[1],
    )
    if normal_enabled:
        assert math.hypot(*vector) == pytest.approx(4)
        assert vector[0] * normal[0] + vector[1] * normal[1] == pytest.approx(4)
    assert result.attachment == attachment
    path = tmp_path / "new-tangency-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (result,)


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_array_member_rotation_preserves_versioned_normal_side(
    batch: bool, legacy: bool, tmp_path: Path
) -> None:
    import math

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    target = LineEntity(uuid4().hex, (5, 0), (15, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    source_ref, target_ref = (
        ArrayEntityRef(sketch.sketch_id, source.entity_id),
        ArrayEntityRef(sketch.sketch_id, target.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(target.entity_id, "start")
        ),
        leader_offsets=((-15, -16),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    group = {
        "array_id": array.array_id,
        "members": [
            {"target": target_ref.to_mapping(), "angle_deg": 120, "center_offset_mm": [0, 0]}
        ],
    }
    command = "drawing.array.batch_override" if batch else "drawing.array.rotate"
    params = {"operation": "rotate", "groups": [group]} if batch else group
    loaded.bus.execute(
        command, params, "local", version=(1 if legacy else 2) if batch else (2 if legacy else 3)
    )
    changed = services.kernel.drawing_datum_identifiers[0]
    offset = changed.leader_offsets[-1]
    vector = (
        changed.position_mm[0] + offset[0] - changed.target_mm[0],
        changed.position_mm[1] + offset[1] - changed.target_mm[1],
    )
    assert vector == pytest.approx((2 * math.sqrt(3), 2) if legacy else (-2 * math.sqrt(3), -2))
    path = tmp_path / f"array-rotate-{batch}-{legacy}.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (changed,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_array_member_replacement_requires_detaching_annotation(owner: str) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    target = LineEntity(uuid4().hex, (5, 0), (15, 0))
    replacement = LineEntity(uuid4().hex, (30, 0), (30, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target, replacement))
    source_ref, target_ref = (
        ArrayEntityRef(sketch.sketch_id, source.entity_id),
        ArrayEntityRef(sketch.sketch_id, target.entity_id),
    )
    replacement_ref = ArrayEntityRef(sketch.sketch_id, replacement.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(target.entity_id, "start")
    )
    if owner == "datum":
        item = DatumIdentifier(uuid4().hex, "A", (20, 20), (5, 0), attachment=attachment)
        params_to_add = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (20, 20),
            leader_target_mm=(5, 0),
            leader_attachment=attachment,
        )
        params_to_add = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params_to_add, "local")
    count = loaded.document.command_count
    replacement_params = {
        "array_id": array.array_id,
        "members": [
            {
                "target": target_ref.to_mapping(),
                "replacement": ArrayReplacement(replacement_ref).to_mapping(),
            }
        ],
    }
    with pytest.raises(ValidationError, match="解除附着"):
        loaded.bus.execute("drawing.array.replace", replacement_params, "local", version=9)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,)
    assert (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    ) == (item,)
    loaded.bus.execute("drawing.array.replace", replacement_params, "local", version=8)
    loaded.bus.undo_operation()
    if isinstance(item, DatumIdentifier):
        detached = replace(item, attachment=None)
        update = {"update_datums": [detached.to_mapping()]}
    else:
        detached = replace(item, leader_attachment=None)
        update = {"update_frames": [detached.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", update, "local")
    loaded.bus.execute("drawing.array.replace", replacement_params, "local", version=9)
    assert services.kernel.associative_arrays[0].members[0].replacement is not None


def test_array_replacement_protects_downstream_attached_member() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 10, 0)) for x in (0, 20, 40, 60))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    arrays = (
        AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            1,
            2,
            0,
            20,
            (refs[0],),
            (ArrayMember(refs[0], refs[1], 0, 1),),
        ),
        AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            1,
            2,
            0,
            20,
            (refs[1],),
            (ArrayMember(refs[1], refs[2], 0, 1),),
        ),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=arrays)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (50, 20),
        (40, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(lines[2].entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="解除附着"):
        loaded.bus.execute(
            "drawing.array.replace",
            {
                "array_id": arrays[0].array_id,
                "members": [
                    {
                        "target": refs[1].to_mapping(),
                        "replacement": ArrayReplacement(refs[3]).to_mapping(),
                    }
                ],
            },
            "local",
            version=9,
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_array_resize_rejects_restoring_lost_attachment(owner: str) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 5, 0)) for x in (0, 10, 20))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        10,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(lines[2].entity_id, "start")
    )
    if owner == "datum":
        item = DatumIdentifier(uuid4().hex, "A", (30, 20), (20, 0), attachment=attachment)
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (30, 20),
            leader_target_mm=(20, 0),
            leader_attachment=attachment,
        )
        params = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params, "local")
    reduced = replace(array, columns=2, members=array.members[:1])
    loaded.bus.execute("drawing.array.resize", {"array": reduced.to_mapping()}, "local", version=16)
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="失关联"):
        loaded.bus.execute(
            "drawing.array.resize", {"array": array.to_mapping()}, "local", version=16
        )
    assert loaded.document.command_count == count
    assert services.kernel.associative_arrays == (reduced,)
    assert (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    ) == (item,)
    loaded.bus.execute("drawing.array.resize", {"array": array.to_mapping()}, "local", version=15)
    assert services.kernel.associative_arrays == (array,)
    loaded.bus.undo_operation()
    if isinstance(item, DatumIdentifier):
        update = {"update_datums": [replace(item, attachment=None).to_mapping()]}
    else:
        update = {"update_frames": [replace(item, leader_attachment=None).to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", update, "local")
    loaded.bus.execute("drawing.array.resize", {"array": array.to_mapping()}, "local", version=16)
    assert services.kernel.associative_arrays == (array,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_array_reset_rejects_replacing_attached_member(owner: str) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    target = LineEntity(uuid4().hex, (5, 0), (15, 0))
    replacement = LineEntity(uuid4().hex, (30, 0), (30, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target, replacement))
    source_ref, target_ref, replacement_ref = tuple(
        ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in (source, target, replacement)
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    loaded.bus.execute(
        "drawing.array.replace",
        {
            "array_id": array.array_id,
            "members": [
                {
                    "target": target_ref.to_mapping(),
                    "replacement": ArrayReplacement(replacement_ref).to_mapping(),
                }
            ],
        },
        "local",
        version=8,
    )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(target.entity_id, "start")
    )
    if owner == "datum":
        item = DatumIdentifier(uuid4().hex, "A", (20, 20), (5, 0), attachment=attachment)
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (20, 20),
            leader_target_mm=(5, 0),
            leader_attachment=attachment,
        )
        params = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params, "local")
    before = services.kernel.sketches
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="解除附着"):
        loaded.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=5)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before
    assert (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    ) == (item,)
    loaded.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=4)
    loaded.bus.undo_operation()
    if isinstance(item, DatumIdentifier):
        update = {"update_datums": [replace(item, attachment=None).to_mapping()]}
    else:
        update = {"update_frames": [replace(item, leader_attachment=None).to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", update, "local")
    loaded.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=5)
    assert services.kernel.associative_arrays[0].members[0].replacement is None


def test_array_reset_requires_detach_before_restoring_lost_member() -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    target = LineEntity(uuid4().hex, (5, 0), (15, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source_ref, target_ref = (
        ArrayEntityRef(sketch.sketch_id, source.entity_id),
        ArrayEntityRef(sketch.sketch_id, target.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(target.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    loaded.bus.execute(
        "drawing.array.erase",
        {"array_id": array.array_id, "targets": [target_ref.to_mapping()]},
        "local",
        version=2,
    )
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="失关联"):
        loaded.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=5)
    assert loaded.document.command_count == count
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)
    loaded.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=4)
    assert services.kernel.datum_attachment_resolved(datum.datum_id)
    loaded.bus.undo_operation()
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)
    detached = replace(datum, attachment=None)
    loaded.bus.execute(
        "drawing.tolerance.batch", {"update_datums": [detached.to_mapping()]}, "local"
    )
    loaded.bus.execute("drawing.array.reset", {"array_id": array.array_id}, "local", version=5)
    assert services.kernel.drawing_datum_identifiers == (detached,)
    assert any(
        entity.entity_id == target.entity_id for entity in services.kernel.sketches[0].entities
    )


def test_array_propagation_rejects_attached_member_reordering() -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    target = PolylineEntity(uuid4().hex, ((5, 0), (15, 0), (15, 10)))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source_ref = ArrayEntityRef(first.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(second.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        first.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (25, 20),
        (10, 0),
        attachment=DatumAttachment(
            second.sketch_id, SketchGeometryReference(target.entity_id, "segment", 0), 0.5, 2
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(first, entities=(replace(source, points_mm=((0, 0), (10, 10), (10, 0))),))
    state = changed.to_state_mapping()
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="重排"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": first.sketch_id,
                        "base_state_sha256": first.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
            version=56,
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (first, second)
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("move_anchor", [False, True])
def test_array_extra_output_source_propagates_normal_protection(
    tmp_path: Path, move_anchor: bool
) -> None:
    import math

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 10, 0)) for x in (0, 5, 30, 5))
    sketches = tuple(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)) for line in lines)
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(
        ArrayEntityRef(sketch.sketch_id, line.entity_id)
        for sketch, line in zip(sketches, lines, strict=True)
    )
    output = ArrayExtraOutput(refs[2], refs[3], refs[0], 0, 1)
    array = AssociativeRectArray(
        uuid4().hex,
        sketches[0].frame,
        1,
        2,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1),),
        extra_outputs=(output,),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local", version=14)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (25, 20),
        (5, 0),
        attachment=DatumAttachment(
            sketches[3].sketch_id, SketchGeometryReference(lines[3].entity_id, "start")
        ),
        leader_offsets=((-20, -16),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    index = 0 if move_anchor else 2
    changed_line = (
        replace(lines[0], start_mm=(2, 0), end_mm=(12, 0))
        if move_anchor
        else replace(lines[2], end_mm=(25, 5 * math.sqrt(3)))
    )
    changed = replace(sketches[index], entities=(changed_line,))
    state = changed.to_state_mapping()
    revisions = [
        {
            "sketch_id": sketches[index].sketch_id,
            "base_state_sha256": sketches[index].local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    assert app.revisions_require_attachment_protection(services, revisions)
    assert app.revisions_require_normal_side_preservation(services, revisions)
    loaded.bus.execute("drawing.sketch.revise", {"revisions": revisions}, "local", version=56)
    result = services.kernel.drawing_datum_identifiers[0]
    offset = result.leader_offsets[-1]
    assert (
        result.position_mm[0] + offset[0] - result.target_mm[0],
        result.position_mm[1] + offset[1] - result.target_mm[1],
    ) == pytest.approx((0, 4) if move_anchor else (-2 * math.sqrt(3), -2))
    if move_anchor:
        assert result.target_mm == pytest.approx((7, 0))
    path = tmp_path / "extra-source-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (result,)


def test_array_replacement_source_propagates_normal_protection(tmp_path: Path) -> None:
    import math

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    target = LineEntity(uuid4().hex, (5, 0), (15, 0))
    replacement = LineEntity(uuid4().hex, (30, 0), (40, 0))
    first, second, third = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
        for entity in (source, target, replacement)
    )
    for sketch in (first, second, third):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source_ref = ArrayEntityRef(first.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(second.sketch_id, target.entity_id)
    replacement_ref = ArrayEntityRef(third.sketch_id, replacement.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        first.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    loaded.bus.execute(
        "drawing.array.replace",
        {
            "array_id": array.array_id,
            "members": [
                {
                    "target": target_ref.to_mapping(),
                    "replacement": ArrayReplacement(replacement_ref).to_mapping(),
                }
            ],
        },
        "local",
        version=8,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (25, 20),
        (5, 0),
        attachment=DatumAttachment(
            second.sketch_id, SketchGeometryReference(target.entity_id, "start")
        ),
        leader_offsets=((-20, -16),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(third, entities=(replace(replacement, end_mm=(25, 5 * math.sqrt(3))),))
    state = changed.to_state_mapping()
    revisions = [
        {
            "sketch_id": third.sketch_id,
            "base_state_sha256": third.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    assert app.revisions_require_attachment_protection(services, revisions)
    assert app.revisions_require_normal_side_preservation(services, revisions)
    loaded.bus.execute("drawing.sketch.revise", {"revisions": revisions}, "local", version=56)
    result = services.kernel.drawing_datum_identifiers[0]
    offset = result.leader_offsets[-1]
    assert (
        result.position_mm[0] + offset[0] - result.target_mm[0],
        result.position_mm[1] + offset[1] - result.target_mm[1],
    ) == pytest.approx((-2 * math.sqrt(3), -2))
    path = tmp_path / "replacement-source-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (result,)


def test_array_propagation_requires_attachment_protection(tmp_path: Path) -> None:
    import math

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    target = LineEntity(uuid4().hex, (5, 0), (15, 0))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source_ref = ArrayEntityRef(first.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(second.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        first.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (25, 20),
        (5, 0),
        attachment=DatumAttachment(
            second.sketch_id, SketchGeometryReference(target.entity_id, "start")
        ),
        leader_offsets=((-20, -16),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(first, entities=(replace(source, end_mm=(-5, 5 * math.sqrt(3))),))
    state = changed.to_state_mapping()
    revisions = [
        {
            "sketch_id": first.sketch_id,
            "base_state_sha256": first.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    assert app.revisions_require_attachment_protection(services, revisions)
    assert app.revisions_require_normal_side_preservation(services, revisions)
    loaded.bus.execute("drawing.sketch.revise", {"revisions": revisions}, "local", version=56)
    result = services.kernel.drawing_datum_identifiers[0]
    offset = result.leader_offsets[-1]
    assert (
        result.position_mm[0] + offset[0] - result.target_mm[0],
        result.position_mm[1] + offset[1] - result.target_mm[1],
    ) == pytest.approx((-2 * math.sqrt(3), -2))
    path = tmp_path / "array-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (result,)


def test_cross_sketch_edit_preserves_attached_normal_side(tmp_path: Path) -> None:
    import math

    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import CircleEntity, LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import rotate_entities

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    original = services.kernel.sketches
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        attachment=DatumAttachment(
            first.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-10, -6),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    proposed = tuple(
        replace(
            sketch,
            entities=rotate_entities(sketch.entities, (sketch.entities[0].entity_id,), (0, 0), 120),
        )
        for sketch in original
    )
    app.commit_cross_sketch_edit(
        services,
        loaded,
        original,
        proposed,
        (
            CrossSketchRef(first.sketch_id, line.entity_id),
            CrossSketchRef(second.sketch_id, circle.entity_id),
        ),
        session_identity=0,
    )
    assert loaded.document.commands[-1].version == 56
    result = services.kernel.drawing_datum_identifiers[0]
    offset = result.leader_offsets[-1]
    assert (result.position_mm[0] + offset[0], result.position_mm[1] + offset[1]) == pytest.approx(
        (-2 * math.sqrt(3), -2)
    )
    path = tmp_path / "cross-normal.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (result,)


def test_multiple_sketch_normal_sides_follow_atomic_revision() -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    sketches: list[Sketch] = []
    datums: list[DatumIdentifier] = []
    revisions: list[dict[str, object]] = []
    for index in range(2):
        line = LineEntity(uuid4().hex, (0, 0), (10, 0))
        sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
        datum = DatumIdentifier(
            uuid4().hex,
            chr(ord("A") + index),
            (10, 10),
            (0, 0),
            attachment=DatumAttachment(
                sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
            ),
            leader_offsets=((-10, -6),),
            leader_auto_normal=True,
        )
        sketches.append(sketch)
        datums.append(datum)
        changed = replace(sketch, entities=(replace(line, end_mm=(-5, 5 * math.sqrt(3))),))
        state = changed.to_state_mapping()
        revisions.append(
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [d.to_mapping() for d in datums]}, "local"
    )
    loaded.bus.execute("drawing.sketch.revise", {"revisions": revisions}, "local", version=56)
    for datum in services.kernel.drawing_datum_identifiers:
        offset = datum.leader_offsets[-1]
        assert (
            datum.position_mm[0] + offset[0],
            datum.position_mm[1] + offset[1],
        ) == pytest.approx((-2 * math.sqrt(3), -2))
    loaded.bus.undo_operation()
    assert services.kernel.sketches == tuple(sketches)
    assert services.kernel.drawing_datum_identifiers == tuple(datums)


def test_negative_normal_side_survives_successive_large_rotations() -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-10, -14),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    for endpoint, expected in (
        ((-5, 5 * math.sqrt(3)), (2 * math.sqrt(3), 2)),
        ((-5, -5 * math.sqrt(3)), (-2 * math.sqrt(3), 2)),
    ):
        changed = replace(sketch, entities=(replace(line, end_mm=endpoint),))
        state = changed.to_state_mapping()
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
            version=56,
        )
        sketch = changed
        updated = services.kernel.drawing_datum_identifiers[0]
        offset = updated.leader_offsets[-1]
        assert (
            updated.position_mm[0] + offset[0],
            updated.position_mm[1] + offset[1],
        ) == pytest.approx(expected)


def test_normal_leader_keeps_length_when_attached_line_rotates(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-10, -6),),
        leader_auto_normal=True,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    moved = replace(sketch, entities=(replace(line, end_mm=(0, 10)),))
    state = moved.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    changed = services.kernel.drawing_datum_identifiers[0]
    vertex = (
        changed.position_mm[0] + changed.leader_offsets[-1][0],
        changed.position_mm[1] + changed.leader_offsets[-1][1],
    )
    assert vertex == pytest.approx((-4, 0))
    path = tmp_path / "normal-rotation.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (changed,)


def test_datum_attached_to_line_interior_follows_line_revision() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (2.5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), parameter=0.25
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    moved = replace(sketch, entities=(replace(line, end_mm=(20, 0)),))
    state = moved.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (5, 0)


@pytest.mark.parametrize("kind", ["start", "end", "geometry"])
def test_line_endpoint_reversal_does_not_silently_retarget_datum(
    kind: Literal["start", "end", "geometry"],
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = {"start": (0, 0), "end": (10, 0), "geometry": (2.5, 0)}[kind]
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        target,
        attachment=DatumAttachment(
            sketch.sketch_id,
            SketchGeometryReference(line.entity_id, kind),
            0.25 if kind == "geometry" else None,
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(line, start_mm=line.end_mm, end_mm=line.start_mm)
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("kind", ["start", "end", "geometry"])
def test_arc_reversal_does_not_silently_retarget_datum(
    kind: Literal["start", "end", "geometry"],
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.sketch import ArcEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 90)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(arc.entity_id, kind),
        0.25 if kind == "geometry" else None,
    )
    target = resolve_attachment_local(attachment, {arc.entity_id: arc})
    assert target is not None
    datum = DatumIdentifier(uuid4().hex, "A", (2, 4), target, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    state = replace(
        sketch, entities=(replace(arc, start_angle_deg=90, sweep_angle_deg=-90),)
    ).to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_arc_center_datum_survives_direction_change() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import ArcEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 90)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(arc.entity_id, "center")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    state = replace(
        sketch, entities=(replace(arc, start_angle_deg=90, sweep_angle_deg=-90),)
    ).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.datum_attachment_resolved(datum.datum_id)


@pytest.mark.parametrize("curve", ["polyline", "spline"])
@pytest.mark.parametrize("kind", ["start", "end"])
def test_curve_endpoint_reordering_does_not_silently_retarget_datum(
    curve: Literal["polyline", "spline"],
    kind: Literal["start", "end"],
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity, SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    points = ((0, 0), (2, 5), (8, 5), (10, 0))
    entity = (
        PolylineEntity(uuid4().hex, points)
        if curve == "polyline"
        else SplineEntity(uuid4().hex, points)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        points[0] if kind == "start" else points[-1],
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entity.entity_id, kind)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = (
        replace(entity, points_mm=tuple(reversed(points)))
        if isinstance(entity, PolylineEntity)
        else replace(entity, control_points_mm=tuple(reversed(points)))
    )
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_deleted_datum_target_is_not_reattached_by_reused_geometry_identity() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    other = LineEntity(uuid4().hex, (0, 10), (10, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, other))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")

    def revise(before: Sketch, entities: tuple[LineEntity, ...]) -> None:
        state = replace(before, entities=entities).to_state_mapping()
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": before.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )

    revise(sketch, (other,))
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)
    reduced = replace(sketch, entities=(other,))
    new_line = replace(line, start_mm=(20, 0), end_mm=(30, 0))
    with pytest.raises(ValidationError, match="附着"):
        revise(reduced, (other, new_line))
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (5, 0)
    loaded.bus.undo()
    assert services.kernel.datum_attachment_resolved(datum.datum_id)


def test_datum_attachment_rejects_same_identity_changed_geometry_type() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import CircleEntity, LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    circle = CircleEntity(line.entity_id, (20, 0), 5)
    state = replace(sketch, entities=(circle,)).to_state_mapping()
    with pytest.raises(ValidationError, match="identity cannot change kind"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_polyline_attachment_becomes_unresolved_when_segment_topology_changes() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (poly,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(poly.entity_id, "segment", 0),
        0.5,
        segment_count=2,
    )
    datum = DatumIdentifier(uuid4().hex, "A", (2, 4), (5, 0), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(
        sketch, entities=(replace(poly, points_mm=((0, 0), (2, 0), (10, 0), (10, 10))),)
    )
    state = changed.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (5, 0)


def test_polyline_segment_count_restoration_does_not_silently_reattach() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (poly,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(poly.entity_id, "segment", 0), 0.5, 2
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")

    def revise(before: Sketch, points: tuple[tuple[int, int], ...]) -> None:
        state = replace(before, entities=(replace(poly, points_mm=points),)).to_state_mapping()
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": before.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )

    expanded_points = ((0, 0), (2, 0), (10, 0), (10, 10))
    revise(sketch, expanded_points)
    expanded = replace(sketch, entities=(replace(poly, points_mm=expanded_points),))
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)
    with pytest.raises(ValidationError, match="附着"):
        revise(expanded, ((0, 0), (2, 0), (10, 10)))
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (5, 0)
    loaded.bus.undo()
    assert services.kernel.datum_attachment_resolved(datum.datum_id)
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (5, 0)


def test_frame_polyline_segment_count_restoration_does_not_silently_reattach() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (poly,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(poly.entity_id, "segment", 0), 0.5, 2
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(5, 0),
        leader_attachment=attachment,
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")

    def revise(before: Sketch, points: tuple[tuple[int, int], ...]) -> Sketch:
        after = replace(before, entities=(replace(poly, points_mm=points),))
        state = after.to_state_mapping()
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": before.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
        return after

    with pytest.raises(ValidationError, match="重排"):
        revise(sketch, ((0, 0), (10, 10), (10, 0)))
    assert services.kernel.drawing_tolerance_frames[0].leader_target_mm == (5, 0)
    expanded = revise(sketch, ((0, 0), (2, 0), (10, 0), (10, 10)))
    with pytest.raises(ValidationError, match="附着"):
        revise(expanded, ((0, 0), (2, 0), (10, 10)))
    assert services.kernel.drawing_tolerance_frames[0].leader_target_mm == (5, 0)
    loaded.bus.undo()
    assert services.kernel.drawing_tolerance_frames[0].leader_target_mm == (5, 0)


def test_frame_rectangle_edge_reversal_requires_detach() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(5, 0),
        leader_attachment=DatumAttachment(
            sketch.sketch_id,
            SketchGeometryReference(rectangle.entity_id, "segment", 0),
            0.5,
            segment_count=4,
            segment_kind="rectangle",
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    changed = replace(sketch, entities=(replace(rectangle, first_corner_mm=(12, 0)),))
    state = changed.to_state_mapping()
    with pytest.raises(ValidationError, match="矩形边"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_legacy_version_one_datum_replays_after_attachment_upgrade(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (2, 4), (0, 0))
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=1
    )
    path = tmp_path / "legacy.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    document = app.open_app_document(reopened, path)
    assert document.document.commands[-1].version == 1
    assert reopened.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize(
    "points",
    [((0, 0), (2, 2), (11, 1), (10, 10)), ((0, 0), (2, 2))],
)
def test_polyline_vertex_attachment_rejects_point_count_changes(
    points: tuple[tuple[int, int], ...],
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (poly,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (10, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(poly.entity_id, "vertex", 1)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    state = replace(sketch, entities=(replace(poly, points_mm=points),)).to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_lost_polyline_vertex_does_not_silently_reattach() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (poly,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (10, 10),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(poly.entity_id, "vertex", 2)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")

    def revise(before: Sketch, points: tuple[tuple[int, int], ...]) -> None:
        state = replace(before, entities=(replace(poly, points_mm=points),)).to_state_mapping()
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": before.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )

    reduced_points = ((0, 0), (10, 0))
    revise(sketch, reduced_points)
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)
    reduced = replace(sketch, entities=(replace(poly, points_mm=reduced_points),))
    with pytest.raises(ValidationError, match="附着"):
        revise(reduced, ((0, 0), (10, 0), (20, 20)))
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (10, 10)
    loaded.bus.undo()
    assert services.kernel.datum_attachment_resolved(datum.datum_id)


@pytest.mark.parametrize(
    "entity_kind,reference_kind",
    [("polyline", "segment"), ("polyline", "vertex"), ("spline", "geometry"), ("spline", "vertex")],
)
def test_translated_partial_curve_reorder_does_not_retarget_datum(
    entity_kind: Literal["polyline", "spline"],
    reference_kind: Literal["segment", "vertex", "geometry"],
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity, SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    points = ((0, 0), (10, 0), (10, 10), (20, 10), (30, 10))
    entity = (
        PolylineEntity(uuid4().hex, points)
        if entity_kind == "polyline"
        else SplineEntity(uuid4().hex, points)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    reference = SketchGeometryReference(
        entity.entity_id, reference_kind, 0 if reference_kind != "geometry" else None
    )
    attachment = DatumAttachment(
        sketch.sketch_id,
        reference,
        0.5 if reference_kind != "vertex" else None,
        segment_count=4 if reference_kind == "segment" else None,
        curve_kind="spline" if reference_kind == "geometry" else None,
        control_count=5 if reference_kind == "geometry" else None,
    )
    target = (
        entity.point_at(0.5)
        if isinstance(entity, SplineEntity) and reference_kind == "geometry"
        else (5, 0)
        if reference_kind == "segment"
        else (0, 0)
    )
    datum = DatumIdentifier(uuid4().hex, "A", (2, 4), target, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    # First two old points swap after a translation; another point deforms.
    changed_points = ((13, 4), (3, 4), (13, 14), (24, 16), (33, 14))
    changed = replace(
        entity,
        **(
            {"points_mm": changed_points}
            if isinstance(entity, PolylineEntity)
            else {"control_points_mm": changed_points}
        ),
    )
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize(
    ("entity_kind", "owner", "reference_kind"),
    [
        ("polyline", "datum", "vertex"),
        ("spline", "datum", "geometry"),
        ("polyline", "frame", "segment"),
    ],
)
@pytest.mark.parametrize("cycle_length", [3, 4, 30])
def test_translated_cycle_with_other_deformation_rejects_retarget(
    entity_kind: Literal["polyline", "spline"],
    owner: Literal["datum", "frame"],
    reference_kind: Literal["vertex", "geometry", "segment"],
    cycle_length: int,
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity, SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    points = (
        ((0.00000000049, 0), (10, 0), (10, 10), (20, 10), (30, 10))
        if cycle_length == 30
        else ((0, 0), (10, 0), (10, 10), (20, 10), (30, 10))
    )
    entity = (
        PolylineEntity(uuid4().hex, points)
        if entity_kind == "polyline"
        else SplineEntity(uuid4().hex, points)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    reference = SketchGeometryReference(
        entity.entity_id, reference_kind, None if reference_kind == "geometry" else 0
    )
    attachment = DatumAttachment(
        sketch.sketch_id,
        reference,
        0.5 if reference_kind != "vertex" else None,
        segment_count=4 if reference_kind == "segment" else None,
        curve_kind="spline" if reference_kind == "geometry" else None,
        control_count=5 if reference_kind == "geometry" else None,
    )
    target = (
        entity.point_at(0.5)
        if isinstance(entity, SplineEntity)
        else ((points[0][0] + points[1][0]) / 2, 0)
        if reference_kind == "segment"
        else points[0]
    )
    if owner == "datum":
        item = DatumIdentifier(uuid4().hex, "A", (2, 4), target, attachment=attachment)
        payload = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (2, 4),
            leader_target_mm=target,
            leader_attachment=attachment,
        )
        payload = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", payload, "local")
    changed_points = (
        ((13, 4), (13, 14), (3, 4), (25, 17), (36, 18))
        if cycle_length == 3
        else ((13, 4), (13, 14), (3.00000000051, 4), (25, 17), (36, 18))
        if cycle_length == 30
        else ((13, 4), (13, 14), (23, 14), (3, 4), (36, 18))
    )
    changed = (
        replace(entity, points_mm=changed_points)
        if isinstance(entity, PolylineEntity)
        else replace(entity, control_points_mm=changed_points)
    )
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    count = loaded.document.command_count
    original_annotations = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches == (sketch,)
    assert (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    ) == original_annotations


def test_historical_three_cycle_replays_without_new_edit_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.geom import kernel

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10), (30, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(polyline.entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(polyline, points_mm=((13, 4), (13, 14), (3, 4), (25, 17), (36, 18)))
    state = replace(sketch, entities=(changed,)).to_state_mapping()

    def previous_guard(*_args: object) -> bool:
        return False

    with monkeypatch.context() as previous:
        previous.setattr(kernel, "_translated_curve_cycle_may_retarget", previous_guard)
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    expected = services.kernel.drawing_datum_identifiers
    loaded.bus.undo()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo()
    assert services.kernel.drawing_datum_identifiers == expected
    path = tmp_path / "historical-cycle.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == expected


def test_unrelated_duplicate_polyline_vertex_does_not_block_safe_edit() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 0), (10, 10), (30, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(polyline.entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(polyline, points_mm=((0, 0), (11, 0), (10, 10), (22, -1), (10, 10), (30, 10)))
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    assert services.kernel.sketches[0].entities == (changed,)
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize(
    "entity_kind,reference_kind",
    [("polyline", "segment"), ("polyline", "vertex"), ("spline", "geometry"), ("spline", "vertex")],
)
@pytest.mark.parametrize("stationary_reference", [False, True, "boundary"])
def test_translated_curve_pair_swap_with_no_fixed_anchors_is_rejected(
    entity_kind: Literal["polyline", "spline"],
    reference_kind: Literal["segment", "vertex", "geometry"],
    stationary_reference: bool | Literal["boundary"],
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity, SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    points = (
        ((0.00000000049, 0), (10, 0), (10, 10), (20, 10), (30, 10))
        if stationary_reference == "boundary"
        else ((0, 0), (10, 0), (10, 10), (20, 10), (30, 10))
    )
    entity = (
        PolylineEntity(uuid4().hex, points)
        if entity_kind == "polyline"
        else SplineEntity(uuid4().hex, points)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    reference = SketchGeometryReference(
        entity.entity_id, reference_kind, 0 if reference_kind != "geometry" else None
    )
    attachment = DatumAttachment(
        sketch.sketch_id,
        reference,
        0.5 if reference_kind != "vertex" else None,
        segment_count=4 if reference_kind == "segment" else None,
        curve_kind="spline" if reference_kind == "geometry" else None,
        control_count=5 if reference_kind == "geometry" else None,
    )
    target = (
        entity.point_at(0.5)
        if isinstance(entity, SplineEntity) and reference_kind == "geometry"
        else (5, 0)
        if reference_kind == "segment"
        else (0, 0)
    )
    datum = DatumIdentifier(uuid4().hex, "A", (2, 4), target, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    original_datums = services.kernel.drawing_datum_identifiers
    command_count = loaded.document.command_count
    # The first two points swap under one translation. All other displacements differ.
    changed_points = (
        ((0, 0), (-10, 0), (14, 15), (25, 17), (36, 18))
        if stationary_reference is True
        else ((13, 4), (3.00000000051, 4), (14, 15), (25, 17), (36, 18))
        if stationary_reference == "boundary"
        else ((13, 4), (3, 4), (14, 15), (25, 17), (36, 18))
    )
    changed = (
        replace(entity, points_mm=changed_points)
        if isinstance(entity, PolylineEntity)
        else replace(entity, control_points_mm=changed_points)
    )
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert loaded.document.command_count == command_count
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_datum_identifiers == original_datums


@pytest.mark.parametrize(
    "entity_kind,reference_kind",
    [("polyline", "segment"), ("polyline", "vertex"), ("spline", "geometry"), ("spline", "vertex")],
)
def test_curve_single_point_edit_across_stationary_datum_is_allowed(
    entity_kind: Literal["polyline", "spline"],
    reference_kind: Literal["segment", "vertex", "geometry"],
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity, SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    points = ((0, 0), (10, 0), (10, 10), (20, 10), (30, 10))
    entity = (
        PolylineEntity(uuid4().hex, points)
        if entity_kind == "polyline"
        else SplineEntity(uuid4().hex, points)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    reference = SketchGeometryReference(
        entity.entity_id, reference_kind, 0 if reference_kind != "geometry" else None
    )
    attachment = DatumAttachment(
        sketch.sketch_id,
        reference,
        0.5 if reference_kind != "vertex" else None,
        segment_count=4 if reference_kind == "segment" else None,
        curve_kind="spline" if reference_kind == "geometry" else None,
        control_count=5 if reference_kind == "geometry" else None,
    )
    target = (
        entity.point_at(0.5)
        if isinstance(entity, SplineEntity) and reference_kind == "geometry"
        else (5, 0)
        if reference_kind == "segment"
        else (0, 0)
    )
    datum = DatumIdentifier(uuid4().hex, "A", (2, 4), target, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed_points = ((0, 0), (-10, 0), *points[2:])
    changed = (
        replace(entity, points_mm=changed_points)
        if isinstance(entity, PolylineEntity)
        else replace(entity, control_points_mm=changed_points)
    )
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment == attachment
    assert services.kernel.datum_attachment_resolved(datum.datum_id)
    expected = (
        changed.point_at(0.5)
        if isinstance(changed, SplineEntity) and reference_kind == "geometry"
        else (-5, 0)
        if reference_kind == "segment"
        else (0, 0)
    )
    assert updated.target_mm == pytest.approx(expected)
    loaded.bus.undo()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo()
    assert services.kernel.drawing_datum_identifiers == (updated,)


def test_polyline_reordering_does_not_silently_retarget_datum() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (poly,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(poly.entity_id, "segment", 0), 0.5, 2
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(sketch, entities=(replace(poly, points_mm=tuple(reversed(poly.points_mm))),))
    state = changed.to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("kind", ["segment", "vertex"])
def test_partial_polyline_reorder_rejects_ambiguous_datum_attachment(
    kind: Literal["segment", "vertex"],
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (poly,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(poly.entity_id, kind, 0),
        0.5 if kind == "segment" else None,
        segment_count=3 if kind == "segment" else None,
    )
    target = (5, 0) if kind == "segment" else (0, 0)
    datum = DatumIdentifier(uuid4().hex, "A", (2, 4), target, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(poly, points_mm=((10, 0), (0, 0), (12, 12), (20, 10)))
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet

    candidate = app.create_replay_candidate(services, loaded, session_identity=0)
    candidate.stage(
        ReplayChangeSet(
            (),
            (
                ReplayAppend(
                    "drawing.sketch.revise",
                    3,
                    {
                        "revisions": [
                            {
                                "sketch_id": sketch.sketch_id,
                                "base_state_sha256": sketch.local_state_digest(),
                                "entities": state["entities"],
                                "constraints": state["constraints"],
                            }
                        ]
                    },
                    "local",
                ),
            ),
            False,
        ),
        current_session_identity=0,
    )
    preview = candidate.preview(current_session_identity=0)
    assert preview.state == "failed"
    assert preview.failure is not None and "附着" in preview.failure.reason


@pytest.mark.parametrize("initially_closed", [False, True])
def test_polyline_open_closed_revision_with_same_segment_count_rejects_retarget(
    initially_closed: bool,
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    points = ((0, 0), (10, 0), (10, 10))
    initial_points = points if initially_closed else (*points, (20, 10))
    poly = PolylineEntity(uuid4().hex, initial_points, initially_closed)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (poly,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(poly.entity_id, "segment", 2), 0.5, 3
    )
    target = (5, 5) if initially_closed else (15, 10)
    datum = DatumIdentifier(uuid4().hex, "A", (2, 4), target, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    revised_points = (*points, (20, 10)) if initially_closed else points
    changed = replace(poly, points_mm=revised_points, closed=not initially_closed)
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize(
    "entity_kind,reference_kind",
    [
        ("polyline", "segment"),
        ("polyline", "vertex"),
        ("polyline", "end"),
        ("spline", "geometry"),
        ("spline", "vertex"),
        ("spline", "end"),
    ],
)
def test_translated_reordered_curve_rejects_ambiguous_datum_retarget(
    entity_kind: Literal["polyline", "spline"],
    reference_kind: Literal["segment", "vertex", "end", "geometry"],
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity, SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    points = ((0, 0), (4, 8), (12, 6), (20, 0))
    entity = (
        PolylineEntity(uuid4().hex, points)
        if entity_kind == "polyline"
        else SplineEntity(uuid4().hex, points)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    index = 0 if reference_kind in ("segment", "vertex") else None
    reference = SketchGeometryReference(entity.entity_id, reference_kind, index)
    if reference_kind == "segment":
        attachment = DatumAttachment(sketch.sketch_id, reference, 0.5, segment_count=3)
        target = (2, 4)
    elif reference_kind == "geometry":
        attachment = DatumAttachment(
            sketch.sketch_id, reference, 0.25, curve_kind="spline", control_count=4
        )
        assert isinstance(entity, SplineEntity)
        target = entity.point_at(0.25)
    else:
        attachment = DatumAttachment(sketch.sketch_id, reference)
        target = points[-1] if reference_kind == "end" else points[0]
    datum = DatumIdentifier(uuid4().hex, "A", (2, 4), target, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    reordered = tuple((x + 50, y + 20) for x, y in reversed(points))
    changed = (
        replace(entity, points_mm=reordered)
        if isinstance(entity, PolylineEntity)
        else replace(entity, control_points_mm=reordered)
    )
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("entity_kind", ["polyline", "spline"])
def test_curve_attachment_follows_translation_and_undo(entity_kind: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity, SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    points = ((0, 0), (4, 8), (12, 6), (20, 0))
    entity = (
        PolylineEntity(uuid4().hex, points)
        if entity_kind == "polyline"
        else SplineEntity(uuid4().hex, points)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    reference = SketchGeometryReference(entity.entity_id, "vertex", 1)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        points[1],
        attachment=DatumAttachment(sketch.sketch_id, reference),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    moved = tuple((x + 50, y + 20) for x, y in points)
    changed = (
        replace(entity, points_mm=moved)
        if isinstance(entity, PolylineEntity)
        else replace(entity, control_points_mm=moved)
    )
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (54, 28)
    loaded.bus.undo()
    assert services.kernel.drawing_datum_identifiers[0].target_mm == points[1]
    loaded.bus.redo()
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (54, 28)


@pytest.mark.parametrize("entity_kind", ["polyline", "spline"])
@pytest.mark.parametrize("endpoint", ["start", "end"])
def test_curve_endpoint_attachment_rejects_count_change_with_moved_endpoint(
    entity_kind: Literal["polyline", "spline"], endpoint: Literal["start", "end"]
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity, SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    points = ((0, 0), (4, 8), (12, 6), (20, 0))
    entity = (
        PolylineEntity(uuid4().hex, points)
        if entity_kind == "polyline"
        else SplineEntity(uuid4().hex, points)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = points[0] if endpoint == "start" else points[-1]
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        target,
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entity.entity_id, endpoint)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed_points = (
        ((-5, -1), (1, 1), (4, 8), (12, 6), (20, 0))
        if endpoint == "start"
        else ((0, 0), (4, 8), (12, 6), (21, 1), (25, 0))
    )
    changed = (
        replace(entity, points_mm=changed_points)
        if isinstance(entity, PolylineEntity)
        else replace(entity, control_points_mm=changed_points)
    )
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_polyline_revision_guard_allows_movement_and_historical_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.geom.kernel import BuildKernel

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (poly,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(poly.entity_id, "segment", 0), 0.5, 3
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")

    def revision(before: Sketch, after: PolylineEntity) -> dict[str, object]:
        state = replace(before, entities=(after,)).to_state_mapping()
        return {
            "revisions": [
                {
                    "sketch_id": before.sketch_id,
                    "base_state_sha256": before.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        }

    moved = replace(poly, points_mm=((1, 1), (11, 1), (11, 11), (21, 11)))
    loaded.bus.execute("drawing.sketch.revise", revision(sketch, moved), "local")
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (6, 1)
    moved_sketch = replace(sketch, entities=(moved,))
    reordered = replace(moved, points_mm=((11, 1), (1, 1), (13, 13), (21, 11)))

    # Simulate an archive written before the admission check existed.
    def legacy_guard(*_args: object) -> None:
        pass

    with monkeypatch.context() as patch:
        patch.setattr(BuildKernel, "validate_datum_revision", legacy_guard)
        loaded.bus.execute("drawing.sketch.revise", revision(moved_sketch, reordered), "local")
    path = tmp_path / "legacy-reorder.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    document = app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers[0].target_mm == (6, 1)
    document.bus.undo()
    document.bus.redo()
    assert reopened.kernel.drawing_datum_identifiers[0].target_mm == (6, 1)


def test_history_edit_rejects_polyline_reorder_and_restores_document() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.replay_proposal import ReplayChangeSet, ReplayEdit
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (poly,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(poly.entity_id, "segment", 0), 0.5, 3
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")

    def revision(entity: PolylineEntity) -> dict[str, object]:
        state = replace(sketch, entities=(entity,)).to_state_mapping()
        return {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        }

    moved = replace(poly, points_mm=((1, 1), (11, 1), (11, 11), (21, 11)))
    loaded.bus.execute("drawing.sketch.revise", revision(moved), "local")
    command = loaded.document.commands[-1]
    bad = replace(poly, points_mm=((10, 0), (0, 0), (12, 12), (20, 10)))
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.edit_and_replay(command.ordinal, revision(bad), "local", "test")
    assert loaded.document.commands[-1] == command
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (6, 1)

    candidate = app.create_replay_candidate(services, loaded, session_identity=0)
    candidate.stage(
        ReplayChangeSet((ReplayEdit(command.ordinal, revision(bad), "local", "test"),), (), False),
        current_session_identity=0,
    )
    preview = candidate.preview(current_session_identity=0)
    assert preview.state == "failed"
    assert preview.failure is not None and "附着" in preview.failure.reason
    assert loaded.document.commands[-1] == command


def test_versioned_guard_checks_topology_evidence_without_relaxing_old_guard() -> None:
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    state = sketch.to_state_mapping()
    mapping = PolylineTopologyMap(polyline.entity_id, (0, 1, 2), 3, False)
    revision: dict[str, object] = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    params: dict[str, object] = {
        "revisions": [revision],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    services.kernel.validate_datum_revision_versioned("drawing.sketch.revise", params, 57)
    bad = PolylineTopologyMap(polyline.entity_id, (2, 1, 0), 3, False)
    params["polyline_topology_maps"] = [
        {"sketch_id": sketch.sketch_id, "mapping": bad.to_mapping()}
    ]
    with pytest.raises(ValidationError, match="拓扑"):
        services.kernel.validate_datum_revision_versioned("drawing.sketch.revise", params, 57)
    # Old versions must not interpret the extra field as permission to bypass protection.
    services.kernel.validate_datum_revision_versioned("drawing.sketch.revise", params, 56)


@pytest.mark.parametrize("mode", ["plain", "normal", "surface"])
def test_explicit_polyline_reorder_preserves_annotations_and_history(
    tmp_path: Path, mode: str
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(polyline.entity_id, "segment", 0), 0.25, 2
    )
    normal = mode == "normal"
    surface = (
        SurfaceIndication((5, 5), (10, 5), 0.5, ((0, 3),), auto_normal=True)
        if mode == "surface"
        else None
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 6),
        (2.5, 0),
        attachment=attachment,
        leader_offsets=((0.5, -3),) if normal else (),
        leader_auto_normal=normal,
        surface_indication=surface,
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (4, 6),
        leader_target_mm=(2.5, 0),
        leader_attachment=attachment,
        leader_anchor_offset=(0, -2),
        leader_offsets=((-1.5, -3),) if normal else (),
        leader_auto_normal=normal,
        surface_indication=surface,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
        version=21 if mode != "plain" else 10,
    )
    reverse = replace(polyline, points_mm=tuple(reversed(polyline.points_mm)))
    state = replace(sketch, entities=(reverse,)).to_state_mapping()
    mapping = PolylineTopologyMap(polyline.entity_id, (2, 1, 0), 3, False)
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ],
            "polyline_topology_maps": [
                {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
            ],
        },
        "local",
        version=57,
    )
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 1
    assert updated.attachment.parameter == 0.75 and updated.target_mm == pytest.approx((2.5, 0))
    assert updated_frame.leader_attachment == updated.attachment
    assert updated.leader_offsets == datum.leader_offsets
    assert updated_frame.leader_offsets == frame.leader_offsets
    assert updated.surface_indication == datum.surface_indication
    assert updated_frame.surface_indication == frame.surface_indication
    path = tmp_path / "reorder.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)
    if mode == "plain":
        from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

        dxf_path = tmp_path / "reorder.dxf"
        write_sketches_dxf(
            services.kernel.sketches,
            dxf_path,
            datum_identifiers=(updated,),
            tolerance_frames=(updated_frame,),
        )
        imported = read_sketch_dxf(dxf_path)
        assert imported.datum_identifiers[0].attachment == updated.attachment
        assert imported.tolerance_frames[0].leader_attachment == updated_frame.leader_attachment
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated,)


def test_polyline_reorder_rejects_untrusted_evidence_and_locked_annotation() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    layers = services.kernel.drawing_layers.add(SketchLayer("GDT"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(polyline.entity_id, "segment", 0), 0.5, 2
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (5, 5), (5, 0), layer_name="GDT", attachment=attachment
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    reverse = replace(polyline, points_mm=tuple(reversed(polyline.points_mm)))
    state = replace(sketch, entities=(reverse,)).to_state_mapping()
    mapping = PolylineTopologyMap(polyline.entity_id, (2, 1, 0), 3, False)
    params: dict[str, object] = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    initial_count = loaded.document.command_count
    wrong = {
        **params,
        "polyline_topology_maps": [
            {
                "sketch_id": sketch.sketch_id,
                "mapping": {**mapping.to_mapping(), "old_to_new": [0, 1, 2]},
            }
        ],
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", wrong, "local", version=57)
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=56)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise", {**params, "dimension": {}}, "local", version=57
        )
    assert loaded.document.command_count == initial_count
    assert services.kernel.sketches[0].entities == (polyline,)

    assert services.kernel.drawing_datum_identifiers == (datum,)
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "GDT" else layer for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    current = services.kernel.sketches[0]
    current_state = replace(current, entities=(reverse,)).to_state_mapping()
    params["revisions"] = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": current_state["entities"],
            "constraints": current_state["constraints"],
        }
    ]
    locked_count = loaded.document.command_count
    with pytest.raises(ValidationError, match="锁定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=57)
    assert loaded.document.command_count == locked_count
    assert services.kernel.sketches[0].entities == (polyline,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    source_locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "0" else layer for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": source_locked.to_mapping(), "dimension_layer": "DIM"},
        "local",
    )
    current = services.kernel.sketches[0]
    current_state = replace(current, entities=(reverse,)).to_state_mapping()
    params["revisions"] = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": current_state["entities"],
            "constraints": current_state["constraints"],
        }
    ]
    locked_count = loaded.document.command_count
    with pytest.raises(ValidationError, match="锁定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=57)
    assert loaded.document.command_count == locked_count
    assert services.kernel.sketches[0].entities == (polyline,)


def test_polyline_reorder_rejects_existing_segment_constraint() -> None:
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    constraint = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(polyline.entity_id, "segment", 0),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,), (constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    current = services.kernel.sketches[0]
    reverse = replace(polyline, points_mm=tuple(reversed(polyline.points_mm)))
    state = replace(current, entities=(reverse,)).to_state_mapping()
    mapping = PolylineTopologyMap(polyline.entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=57)
    assert loaded.document.command_count == count
    assert services.kernel.sketches[0] == current


@pytest.mark.parametrize("mode", ["normal", "surface"])
def test_midpoint_reverse_keeps_normal_on_same_physical_side(mode: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(polyline.entity_id, "segment", 0), 0.5, 1
    )
    surface = (
        SurfaceIndication((5, 5), (10, 5), 0.5, ((0, 3),), auto_normal=True)
        if mode == "surface"
        else None
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 6),
        (5, 0),
        attachment=attachment,
        leader_offsets=((0, -3),) if mode == "normal" else (),
        leader_auto_normal=mode == "normal",
        surface_indication=surface,
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 6),
        leader_target_mm=(5, 0),
        leader_attachment=attachment,
        leader_offsets=((0, -3),) if mode == "normal" else (),
        leader_auto_normal=mode == "normal",
        surface_indication=surface,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
        version=21,
    )
    reverse = replace(polyline, points_mm=tuple(reversed(polyline.points_mm)))
    state = replace(sketch, entities=(reverse,)).to_state_mapping()
    mapping = PolylineTopologyMap(polyline.entity_id, (1, 0), 2, False)
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ],
            "polyline_topology_maps": [
                {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
            ],
        },
        "local",
        version=57,
    )
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment == datum.attachment
    assert updated.leader_offsets == datum.leader_offsets
    assert updated.surface_indication == datum.surface_indication
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert updated_frame.leader_attachment == frame.leader_attachment
    assert updated_frame.leader_offsets == frame.leader_offsets
    assert updated_frame.surface_indication == frame.surface_indication


def test_copied_geometry_and_annotations_commit_as_one_undoable_transaction() -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_copy import copy_geometric_annotations
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("inspect", "检验字体", height_mm=7)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    source_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, source_sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 5),
        (0, 0),
        attachment=DatumAttachment(
            source_sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        text_style_id="inspect",
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (10, 5),
        text_style_id="inspect",
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    cloned_line = replace(line, entity_id=uuid4().hex, start_mm=(20, 0), end_mm=(30, 0))
    copied_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (cloned_line,))
    frames, datums = copy_geometric_annotations(
        (frame,),
        (datum,),
        {(source_sketch.sketch_id, line.entity_id): cloned_line.entity_id},
        copied_sketch.sketch_id,
        (20, 0),
        {datum.datum_id: "B"},
        preserve_external=True,
    )
    app.commit_new_sketch(
        services,
        loaded,
        copied_sketch,
        session_identity=0,
        imported_tolerance_frames=frames,
        imported_datums=datums,
    )
    assert len(services.kernel.sketches) == 2
    assert (
        services.kernel.drawing_tolerance_frames[-1].rows[0].datums[0].datum_id
        == datums[0].datum_id
    )
    assert services.kernel.datum_attachment_resolved(datums[0].datum_id)
    assert services.kernel.drawing_tolerance_frames[-1].text_style_id == "inspect"
    assert services.kernel.drawing_datum_identifiers[-1].text_style_id == "inspect"
    loaded.bus.undo_operation()
    assert services.kernel.sketches == (source_sketch,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_tolerance_frames[-1].text_style_id == "inspect"
    assert services.kernel.drawing_datum_identifiers[-1].text_style_id == "inspect"
    assert services.kernel.datum_attachment_resolved(datums[0].datum_id)


def test_same_document_mixed_copy_preserves_reference_to_uncopied_datum() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "A", (0, 2), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (5, 5),
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
        session_identity=0,
        imported_tolerance_frames=(frame,),
        preserve_existing_datum_refs=True,
    )
    assert services.kernel.drawing_tolerance_frames[0].rows[0].datums[0].datum_id == datum.datum_id


@pytest.mark.parametrize("include_geometry", [False, True])
def test_mixed_move_surface_indication_respects_target(include_geometry: bool) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.geometric_tolerance_geometry import surface_indication_geometry
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    surface = SurfaceIndication((3, 8), (8, 8), 0.5, ((1, 4),))
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 20), (5, 0), attachment=attachment, surface_indication=surface
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    app.move_tolerance_selection(
        services,
        loaded,
        (line.entity_id,) if include_geometry else (),
        (),
        (datum.datum_id,),
        (),
        (5, 3),
        session_identity=0,
    )
    moved = services.kernel.drawing_datum_identifiers[0]
    expected = (10, 3) if include_geometry else (5, 0)
    assert moved.target_mm == expected
    assert moved.surface_indication == surface
    assert surface_indication_geometry(moved.target_mm, surface)[0][0] == (
        expected[0] + 3,
        expected[1] + 8,
    )
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_mixed_move_geometry_and_annotations_is_one_undoable_operation() -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("inspect", "检验字体", height_mm=7)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), style)).to_mapping(), "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 5),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        text_style_id="inspect",
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (10, 5),
        text_style_id="inspect",
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    app.move_tolerance_selection(
        services,
        loaded,
        (line.entity_id,),
        (frame.frame_id,),
        (datum.datum_id,),
        (),
        (5, 3),
        session_identity=0,
    )
    moved_line = services.kernel.sketches[0].entities[0]
    assert isinstance(moved_line, LineEntity)
    assert moved_line.start_mm == (5, 3)
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (5, 3)
    assert services.kernel.drawing_datum_identifiers[0].position_mm == (5, 8)
    assert services.kernel.drawing_tolerance_frames[0].position_mm == (15, 8)
    assert services.kernel.drawing_tolerance_frames[0].text_style_id == "inspect"
    assert services.kernel.drawing_datum_identifiers[0].text_style_id == "inspect"
    loaded.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_tolerance_frames[0].text_style_id == "inspect"
    assert services.kernel.drawing_datum_identifiers[0].text_style_id == "inspect"
    assert services.kernel.datum_attachment_resolved(datum.datum_id)


def test_mixed_move_frame_and_attached_geometry_is_atomic() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    app.move_tolerance_selection(
        services, loaded, (line.entity_id,), (frame.frame_id,), (), (), (5, 3), session_identity=0
    )
    moved = services.kernel.drawing_tolerance_frames[0]
    assert moved.position_mm == (15, 13) and moved.leader_target_mm == (5, 3)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_mixed_move_updates_unselected_datum_target_but_not_its_label_position() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 5),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (10, 5))
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    app.move_tolerance_selection(
        services, loaded, (line.entity_id,), (frame.frame_id,), (), (), (5, 3), session_identity=0
    )
    after = services.kernel.drawing_datum_identifiers[0]
    assert after.position_mm == datum.position_mm and after.target_mm == (5, 3)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_mixed_move_preserves_internal_dimension_and_moves_its_label() -> None:
    from mycad.core.dimension_tolerance import DimensionTolerance
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(5, 5),
        tolerance=DimensionTolerance("symmetric", 0.1, -0.1),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (10, 5))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    app.move_tolerance_selection(
        services, loaded, (line.entity_id,), (frame.frame_id,), (), (), (5, 3), session_identity=0
    )
    moved = services.kernel.sketches[0].constraints[0]
    assert moved.position_mm == (10, 8)
    assert moved.tolerance == dimension.tolerance and moved.value == 10
    loaded.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)


@pytest.mark.parametrize("version,modified", [(53, False), (54, True)])
def test_rigid_dimension_revision_rejects_old_version_and_unrelated_edits(
    version: int, modified: bool
) -> None:
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(5, 5),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    moved = replace(
        sketch,
        entities=(replace(line, start_mm=(5, 3), end_mm=(15, 3)),),
        constraints=(replace(dimension, position_mm=(10, 8), precision=3 if modified else 2),),
    )
    state = moved.to_state_mapping()
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ]
    }
    with pytest.raises(ValidationError, match="modified constraints"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=version)
    assert services.kernel.sketches == (sketch,)


def test_mixed_move_rejects_locked_dimension_layer() -> None:
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(5, 5),
        layer_name="DIM",
    )
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,), services.kernel.drawing_layers
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    locked = replace(
        services.kernel.drawing_layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "DIM" else layer
            for layer in services.kernel.drawing_layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    before = services.kernel.sketches
    with pytest.raises(ValidationError):
        app.move_tolerance_selection(
            services, loaded, (line.entity_id,), (), (), (), (5, 3), session_identity=0
        )
    assert services.kernel.sketches == before


def test_mixed_move_accepts_fractional_dimension_displacement() -> None:
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0.1, 0), (1.1, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        1,
        "mm",
        driving=False,
        position_mm=(0.3, 2),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    app.move_tolerance_selection(
        services, loaded, (line.entity_id,), (), (), (), (0.1, 0), session_identity=0
    )
    assert services.kernel.sketches[0].constraints[0].position_mm == pytest.approx((0.4, 2))
    loaded.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)


def test_rectangle_edge_datum_replays_and_rejects_reversal(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 6))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (12, 3),
        (10, 3),
        attachment=DatumAttachment(
            sketch.sketch_id,
            SketchGeometryReference(rectangle.entity_id, "segment", 1),
            0.5,
            4,
            segment_kind="rectangle",
        ),
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=2
        )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=3
    )
    dxf_path = tmp_path / "rectangle-datum.dxf"
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    write_sketches_dxf((sketch,), dxf_path, datum_identifiers=(datum,))
    imported = read_sketch_dxf(dxf_path)
    assert imported.datum_identifiers[0].attachment == datum.attachment
    app.move_tolerance_selection(
        services, loaded, (rectangle.entity_id,), (), (), (), (5, 2), session_identity=0
    )
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (15, 5)
    current = services.kernel.sketches[0]
    flipped = replace(
        current, entities=(replace(rectangle, first_corner_mm=(15, 2), opposite_corner_mm=(5, 8)),)
    )
    state = flipped.to_state_mapping()
    revision = {
        "sketch_id": current.sketch_id,
        "base_state_sha256": current.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    with pytest.raises(ValidationError, match="矩形边方向"):
        loaded.bus.execute("drawing.sketch.revise", {"revisions": [revision]}, "local", version=54)
    path = tmp_path / "rectangle-datum.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers[0].target_mm == (15, 5)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_spline_datum_loses_association_when_control_count_changes(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    spline = SplineEntity(uuid4().hex, ((0, 0), (2, 5), (8, 5), (10, 0)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = spline.point_at(0.5)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 10),
        target,
        attachment=DatumAttachment(
            sketch.sketch_id,
            SketchGeometryReference(spline.entity_id, "geometry"),
            0.5,
            curve_kind="spline",
            control_count=4,
        ),
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=3
        )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=4
    )
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    dxf_path = tmp_path / "spline-datum.dxf"
    write_sketches_dxf((sketch,), dxf_path, datum_identifiers=(datum,))
    assert read_sketch_dxf(dxf_path).datum_identifiers[0].attachment == datum.attachment
    deformed = replace(spline, control_points_mm=((0, 0), (2, 6), (8, 5), (10, 0)))
    deformed_state = replace(sketch, entities=(deformed,)).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": deformed_state["entities"],
                    "constraints": deformed_state["constraints"],
                }
            ]
        },
        "local",
        version=54,
    )
    assert services.kernel.drawing_datum_identifiers[0].target_mm == deformed.point_at(0.5)
    loaded.bus.undo()
    assert services.kernel.drawing_datum_identifiers[0].target_mm == target
    reversed_spline = replace(spline, control_points_mm=tuple(reversed(spline.control_points_mm)))
    reversed_state = replace(sketch, entities=(reversed_spline,)).to_state_mapping()
    with pytest.raises(ValidationError, match="样条控制点发生重排"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": reversed_state["entities"],
                        "constraints": reversed_state["constraints"],
                    }
                ]
            },
            "local",
            version=54,
        )
    changed = replace(
        sketch, entities=(replace(spline, control_points_mm=(*spline.control_points_mm, (12, 0))),)
    )
    state = changed.to_state_mapping()
    revision = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    loaded.bus.execute("drawing.sketch.revise", {"revisions": [revision]}, "local", version=54)
    assert services.kernel.drawing_datum_identifiers[0].target_mm == target
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)
    path = tmp_path / "spline-datum.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert not reopened.kernel.datum_attachment_resolved(datum.datum_id)
    loaded.bus.undo()
    assert services.kernel.datum_attachment_resolved(datum.datum_id)


@pytest.mark.parametrize("kind", ["geometry", "vertex"])
def test_spline_datum_does_not_silently_reattach_after_control_count_restoration(
    kind: Literal["geometry", "vertex"],
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    spline = SplineEntity(uuid4().hex, ((0, 0), (2, 5), (8, 5), (10, 0), (12, 0)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    if kind == "geometry":
        attachment = DatumAttachment(
            sketch.sketch_id,
            SketchGeometryReference(spline.entity_id, "geometry"),
            0.5,
            curve_kind="spline",
            control_count=5,
        )
        target = spline.point_at(0.5)
    else:
        attachment = DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(spline.entity_id, "vertex", 4)
        )
        target = spline.control_points_mm[4]
    datum = DatumIdentifier(uuid4().hex, "A", (5, 10), target, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")

    def revise(before: Sketch, points: tuple[tuple[int, int], ...]) -> None:
        state = replace(
            before, entities=(replace(spline, control_points_mm=points),)
        ).to_state_mapping()
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": before.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )

    reduced_points = ((0, 0), (2, 5), (8, 5), (10, 0))
    revise(sketch, reduced_points)
    assert not services.kernel.datum_attachment_resolved(datum.datum_id)
    reduced = replace(sketch, entities=(replace(spline, control_points_mm=reduced_points),))
    with pytest.raises(ValidationError, match="附着"):
        revise(reduced, ((0, 0), (2, 5), (8, 5), (10, 0), (20, 20)))
    assert services.kernel.drawing_datum_identifiers[0].target_mm == target
    loaded.bus.undo()
    assert services.kernel.datum_attachment_resolved(datum.datum_id)


@pytest.mark.parametrize("kind", ["geometry", "vertex"])
def test_spline_partial_control_point_reordering_rejects_datum_retarget(
    kind: Literal["geometry", "vertex"],
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    spline = SplineEntity(uuid4().hex, ((0, 0), (2, 5), (8, 5), (10, 0), (12, 0)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = (
        DatumAttachment(
            sketch.sketch_id,
            SketchGeometryReference(spline.entity_id, "geometry"),
            0.5,
            curve_kind="spline",
            control_count=5,
        )
        if kind == "geometry"
        else DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(spline.entity_id, "vertex", 1)
        )
    )
    target = spline.point_at(0.5) if kind == "geometry" else spline.control_points_mm[1]
    datum = DatumIdentifier(uuid4().hex, "A", (5, 10), target, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed = replace(spline, control_points_mm=((0, 0), (8, 5), (2, 5), (11, 0), (12, 0)))
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    with pytest.raises(ValidationError, match="样条控制点发生重排"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("kind", ["polyline", "spline"])
def test_datum_rejects_ambiguous_duplicate_control_point_change(
    kind: Literal["polyline", "spline"],
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import PolylineEntity, SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    points = ((0, 0), (10, 0), (0, 0), (10, 10), (20, 10))
    entity = (
        PolylineEntity(uuid4().hex, points)
        if kind == "polyline"
        else SplineEntity(uuid4().hex, points)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = (
        DatumAttachment(sketch.sketch_id, SketchGeometryReference(entity.entity_id, "vertex", 0))
        if isinstance(entity, PolylineEntity)
        else DatumAttachment(
            sketch.sketch_id,
            SketchGeometryReference(entity.entity_id, "geometry"),
            0.5,
            curve_kind="spline",
            control_count=5,
        )
    )
    target = (0, 0) if isinstance(entity, PolylineEntity) else entity.point_at(0.5)
    datum = DatumIdentifier(uuid4().hex, "A", (5, 10), target, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    changed_points = ((1, 1), *points[1:])
    changed = (
        replace(entity, points_mm=changed_points)
        if isinstance(entity, PolylineEntity)
        else replace(entity, control_points_mm=changed_points)
    )
    state = replace(sketch, entities=(changed,)).to_state_mapping()
    with pytest.raises(ValidationError, match="附着"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_import_conflicting_datum_label_is_rejected_atomically() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "B", (0, 2), (0, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (5, 5),
    )
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="基准.*标签"):
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
            session_identity=0,
            imported_tolerance_frames=(frame,),
            imported_datums=(datum,),
        )
    assert loaded.document.command_count == count
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_datum_identifiers


def test_preserved_existing_datum_must_match_reference_label() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(uuid4().hex, "B", (0, 2), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (5, 5),
    )
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="基准.*标签"):
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), ()),
            session_identity=0,
            imported_tolerance_frames=(frame,),
            preserve_existing_datum_refs=True,
        )
    assert loaded.document.command_count == count
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert not services.kernel.drawing_tolerance_frames


def test_dxf_label_conflict_import_preserves_unresolved_frame(tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    datum = DatumIdentifier(uuid4().hex, "B", (0, 2), (0, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (5, 5),
    )
    path = tmp_path / "conflicting-link.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(datum,))
    imported = read_sketch_dxf(path)
    assert any("基准关联" in warning for warning in imported.report.warnings)
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    app.commit_new_sketch(
        services,
        loaded,
        imported.sketch,
        session_identity=0,
        imported_tolerance_frames=imported.tolerance_frames,
        imported_datums=imported.datum_identifiers,
    )
    assert services.kernel.drawing_tolerance_frames[0].rows[0].datums == (DatumReference("A"),)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_tolerance_frames
    assert not services.kernel.drawing_datum_identifiers


@pytest.mark.parametrize(
    ("relation_uses_polyline", "same_sketch"), [(False, False), (True, False), (False, True)]
)
def test_reorder_handles_unrelated_tangency_without_weakening_related_protection(
    relation_uses_polyline: bool, same_sketch: bool
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import CircleEntity, LineEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    line = LineEntity(uuid4().hex, (20, 0), (30, 0))
    drawing = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (polyline, line) if same_sketch else (polyline,)
    )
    unrelated = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    circle = CircleEntity(uuid4().hex, (5, 2) if relation_uses_polyline else (25, 2), 2)
    circle_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (drawing, circle_sketch) if same_sketch else (drawing, unrelated, circle_sketch):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    first = (
        CrossSketchRef(drawing.sketch_id, polyline.entity_id, 0)
        if relation_uses_polyline
        else CrossSketchRef(
            drawing.sketch_id if same_sketch else unrelated.sketch_id, line.entity_id
        )
    )
    relation = CrossSketchTangency(
        uuid4().hex, first, CrossSketchRef(circle_sketch.sketch_id, circle.entity_id), "line_left"
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    current = next(item for item in services.kernel.sketches if item.sketch_id == drawing.sketch_id)
    polyline = next(item for item in current.entities if isinstance(item, PolylineEntity))
    attachment = DatumAttachment(
        current.sketch_id, SketchGeometryReference(polyline.entity_id, "segment", 0), 0.25, 2
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 5), (2.5, 0), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    reverse = replace(polyline, points_mm=tuple(reversed(polyline.points_mm)))
    state = replace(
        current,
        entities=tuple(
            reverse if item.entity_id == polyline.entity_id else item for item in current.entities
        ),
    ).to_state_mapping()
    mapping = PolylineTopologyMap(polyline.entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    if relation_uses_polyline:
        count = loaded.document.command_count
        with pytest.raises(ValidationError):
            loaded.bus.execute("drawing.sketch.revise", params, "local", version=57)
        assert loaded.document.command_count == count
        assert services.kernel.drawing_datum_identifiers == (datum,)
    else:
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=57)
        updated = services.kernel.drawing_datum_identifiers[0]
        assert updated.attachment is not None and updated.attachment.reference.index == 1
        assert updated.target_mm == pytest.approx((2.5, 0))
        assert services.kernel.cross_sketch_tangencies == (relation,)


def test_exact_cyclic_reorder_preserves_segment_constraint_and_annotation() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    constraint = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(polyline.entity_id, "segment", 0),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,), (constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    current = services.kernel.sketches[0]
    attachment = DatumAttachment(
        current.sketch_id, SketchGeometryReference(polyline.entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 5), (2.5, 0), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    rotated = replace(polyline, points_mm=(*polyline.points_mm[1:], polyline.points_mm[0]))
    revised_constraint = replace(
        constraint, references=(SketchGeometryReference(polyline.entity_id, "segment", 3),)
    )
    revised = replace(current, entities=(rotated,), constraints=(revised_constraint,))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(polyline.entity_id, (3, 0, 1, 2), 4, True)
    params: dict[str, object] = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    wrong_constraint = replace(
        constraint, references=(SketchGeometryReference(polyline.entity_id, "segment", 1),)
    )
    wrong_state = replace(revised, constraints=(wrong_constraint,)).to_state_mapping()
    wrong_params = {
        **params,
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": wrong_state["entities"],
                "constraints": wrong_state["constraints"],
            }
        ],
    }
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", wrong_params, "local", version=57)
    assert loaded.document.command_count == count
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=57)
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx((2.5, 0))
    assert services.kernel.sketches[0].constraints == (revised_constraint,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.sketches[0].constraints == (constraint,)


def test_cyclic_reorder_preserves_related_cross_sketch_tangency(tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for item in (sketch, other):
        app.commit_new_sketch(services, loaded, item, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketch.sketch_id, polyline.entity_id, 0),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    current = next(item for item in services.kernel.sketches if item.sketch_id == sketch.sketch_id)
    attachment = DatumAttachment(
        current.sketch_id, SketchGeometryReference(polyline.entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 5), (2.5, 0), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 6),
        leader_target_mm=(2.5, 0),
        leader_attachment=attachment,
        leader_offsets=((-2.5, -3),),
        leader_auto_normal=True,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
        version=21,
    )
    rotated = replace(polyline, points_mm=(*polyline.points_mm[1:], polyline.points_mm[0]))
    state = replace(current, entities=(rotated,)).to_state_mapping()
    mapping = PolylineTopologyMap(polyline.entity_id, (3, 0, 1, 2), 4, True)
    rebound = replace(relation, first=replace(relation.first, segment_index=3))
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
        "remove_tangencies": [relation.relation_id],
        "cross_tangencies": [rebound.to_mapping()],
    }
    wrong = replace(relation, first=replace(relation.first, segment_index=1))
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="相切"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {**params, "cross_tangencies": [wrong.to_mapping()]},
            "local",
            version=57,
        )
    with pytest.raises(ValidationError, match="相切"):
        loaded.bus.execute(
            "drawing.sketch.revise", {**params, "cross_tangencies": []}, "local", version=57
        )
    assert loaded.document.command_count == count
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=57)
    assert services.kernel.cross_sketch_tangencies == (rebound,)
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx((2.5, 0))
    assert updated_frame.leader_attachment == updated.attachment
    assert updated_frame.leader_offsets == frame.leader_offsets
    path = tmp_path / "cyclic-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.cross_sketch_tangencies == (rebound,)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)
    loaded.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.cross_sketch_tangencies == (rebound,)
    assert services.kernel.drawing_datum_identifiers == (updated,)
    assert services.kernel.drawing_tolerance_frames == (updated_frame,)


@pytest.mark.parametrize(
    ("same_sketch", "locked_target"), [(False, False), (True, False), (False, True)]
)
def test_array_source_reorder_preserves_source_and_member_annotations(
    tmp_path: Path, same_sketch: bool, locked_target: bool
) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    target = PolylineEntity(uuid4().hex, ((0, 20), (10, 20), (10, 30)))
    source_sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (source, target) if same_sketch else (source,)
    )
    target_sketch = (
        source_sketch if same_sketch else Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    )
    for sketch in (source_sketch,) if same_sketch else (source_sketch, target_sketch):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source_ref = ArrayEntityRef(source_sketch.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(target_sketch.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        source_sketch.frame,
        2,
        1,
        20,
        0,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 1, 0),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    layers = services.kernel.drawing_layers
    if locked_target:
        layers = layers.add(SketchLayer("GDT"))
        loaded.bus.execute(
            "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    source_attachment = DatumAttachment(
        source_sketch.sketch_id, SketchGeometryReference(source.entity_id, "segment", 0), 0.25, 2
    )
    target_attachment = DatumAttachment(
        target_sketch.sketch_id, SketchGeometryReference(target.entity_id, "segment", 0), 0.25, 2
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 5), (2.5, 0), attachment=source_attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 26),
        leader_target_mm=(2.5, 20),
        leader_attachment=target_attachment,
        leader_offsets=((-2.5, -3),),
        leader_auto_normal=True,
        layer_name="GDT" if locked_target else "0",
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
        version=21,
    )
    if locked_target:
        locked = replace(
            layers,
            layers=tuple(
                replace(layer, locked=True) if layer.name == "GDT" else layer
                for layer in layers.layers
            ),
        )
        loaded.bus.execute(
            "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    current = next(
        item for item in services.kernel.sketches if item.sketch_id == source_sketch.sketch_id
    )
    reverse = replace(source, points_mm=tuple(reversed(source.points_mm)))
    state = replace(
        current,
        entities=tuple(
            reverse if item.entity_id == source.entity_id else item for item in current.entities
        ),
    ).to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    if locked_target:
        count = loaded.document.command_count
        with pytest.raises(ValidationError, match="锁定"):
            loaded.bus.execute("drawing.sketch.revise", params, "local", version=57)
        assert loaded.document.command_count == count
        assert services.kernel.drawing_datum_identifiers == (datum,)
        assert services.kernel.drawing_tolerance_frames == (frame,)
        assert next(
            item for item in services.kernel.sketches if item.sketch_id == source_sketch.sketch_id
        ).entities == (source,)
        assert next(
            item for item in services.kernel.sketches if item.sketch_id == target_sketch.sketch_id
        ).entities == (target,)
        assert services.kernel.associative_arrays == (array,)
        return
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=57)
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 1
    assert (
        updated_frame.leader_attachment is not None
        and updated_frame.leader_attachment.reference.index == 1
    )
    assert updated.target_mm == pytest.approx((2.5, 0))
    assert updated_frame.leader_target_mm == pytest.approx((2.5, 20))
    assert updated_frame.leader_offsets == frame.leader_offsets
    assert services.kernel.associative_arrays == (array,)
    path = tmp_path / "array-reorder.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_tolerance_frames == (updated_frame,)


@pytest.mark.parametrize(
    ("normal", "base_index", "locked"),
    [
        (False, None, False),
        (True, None, False),
        (True, 0, False),
        (True, 1, False),
        (True, 1, True),
    ],
)
def test_rotated_array_reorder_with_unchanged_anchor_preserves_member_attachment(
    tmp_path: Path, normal: bool, base_index: int | None, locked: bool
) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    rotated = rotate_entities((source,), (source.entity_id,), (0, 0), 90)[0]
    translated = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
    assert isinstance(translated, PolylineEntity)
    target = replace(translated, entity_id=uuid4().hex)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    for item in (first, second):
        app.commit_new_sketch(services, loaded, item, session_identity=0)
    a = ArrayEntityRef(first.sketch_id, source.entity_id)
    b = ArrayEntityRef(second.sketch_id, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        first.frame,
        2,
        1,
        20,
        0,
        (a,),
        (ArrayMember(a, b, 1, 0, rotation_deg=90),),
        base_point=ArrayBasePoint(
            source=a, reference=SketchGeometryReference(source.entity_id, "vertex", base_index)
        )
        if base_index is not None
        else None,
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    layers = services.kernel.drawing_layers
    if locked:
        layers = layers.add(SketchLayer("GDT"))
        loaded.bus.execute(
            "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    attachment = DatumAttachment(
        second.sketch_id, SketchGeometryReference(target.entity_id, "segment", 0), 0.25, 4
    )
    point = resolve_attachment_local(attachment, {target.entity_id: target})
    assert point is not None
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 28),
        leader_target_mm=point,
        leader_attachment=attachment,
        leader_offsets=((point[0] - 8, point[1] - 28),) if normal else (),
        leader_auto_normal=normal,
        layer_name="GDT" if locked else "0",
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()]},
        "local",
        version=21 if normal else 10,
    )
    if locked:
        locked_layers = replace(
            layers,
            layers=tuple(
                replace(layer, locked=True) if layer.name == "GDT" else layer
                for layer in layers.layers
            ),
        )
        loaded.bus.execute(
            "drawing.layers.set",
            {"layers": locked_layers.to_mapping(), "dimension_layer": "DIM"},
            "local",
        )
    current = next(item for item in services.kernel.sketches if item.sketch_id == first.sketch_id)
    reverse = replace(source, points_mm=(source.points_mm[0], *reversed(source.points_mm[1:])))
    state = replace(current, entities=(reverse,)).to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    if base_index == 1:
        count = loaded.document.command_count
        with pytest.raises(ValidationError):
            loaded.bus.execute("drawing.sketch.revise", params, "local", version=57)
        assert loaded.document.command_count == count
        assert services.kernel.drawing_tolerance_frames == (frame,)
        assert services.kernel.associative_arrays == (array,)
        assert next(
            item for item in services.kernel.sketches if item.sketch_id == first.sketch_id
        ).entities == (source,)
        assert next(
            item for item in services.kernel.sketches if item.sketch_id == second.sketch_id
        ).entities == (target,)
    if locked:
        count = loaded.document.command_count
        with pytest.raises(ValidationError, match="锁定"):
            loaded.bus.execute("drawing.sketch.revise", params, "local", version=58)
        assert loaded.document.command_count == count
        assert services.kernel.associative_arrays == (array,)
        assert services.kernel.drawing_tolerance_frames == (frame,)
        assert next(
            item for item in services.kernel.sketches if item.sketch_id == first.sketch_id
        ).entities == (source,)
        assert next(
            item for item in services.kernel.sketches if item.sketch_id == second.sketch_id
        ).entities == (target,)
        return
    loaded.bus.execute(
        "drawing.sketch.revise", params, "local", version=58 if base_index == 1 else 57
    )
    updated = services.kernel.drawing_tolerance_frames[0]
    assert updated.leader_attachment is not None and updated.leader_attachment.reference.index == 3
    assert updated.leader_target_mm == pytest.approx(point)
    assert updated.leader_offsets == frame.leader_offsets
    updated_array = services.kernel.associative_arrays[0]
    if base_index == 1:
        assert (
            updated_array.base_point is not None and updated_array.base_point.reference is not None
        )
        assert updated_array.base_point.reference.index == 3
    else:
        assert updated_array == array
    path = tmp_path / "rotated-array-reorder.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (updated,)
    assert reopened.kernel.associative_arrays == (updated_array,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.associative_arrays == (array,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_tolerance_frames == (updated,)
    assert services.kernel.associative_arrays == (updated_array,)


@pytest.mark.parametrize(
    ("stable_anchor", "with_tangency"), [(True, False), (False, False), (True, True)]
)
def test_array_replacement_reorder_preserves_existing_member_geometry(
    tmp_path: Path, stable_anchor: bool, with_tangency: bool
) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    replacement = PolylineEntity(uuid4().hex, ((30, 0), (40, 0), (40, 10), (30, 10)), closed=True)
    target = PolylineEntity(uuid4().hex, ((0, 20), (10, 20), (10, 30), (0, 30)), closed=True)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (replacement,))
    last = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    for sketch in (first, other, last):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    a = ArrayEntityRef(first.sketch_id, source.entity_id)
    b = ArrayEntityRef(last.sketch_id, target.entity_id)
    replacement_ref = ArrayEntityRef(other.sketch_id, replacement.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        first.frame,
        2,
        1,
        20,
        0,
        (a,),
        (ArrayMember(a, b, 1, 0, replacement=ArrayReplacement(replacement_ref)),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation: CrossSketchTangency | None = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 22), 2)
        circle_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, circle_sketch, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(last.sketch_id, target.entity_id, 0),
            CrossSketchRef(circle_sketch.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    first_attachment = DatumAttachment(
        first.sketch_id, SketchGeometryReference(source.entity_id, "segment", 0), 0.25, 4
    )
    last_attachment = DatumAttachment(
        last.sketch_id, SketchGeometryReference(target.entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 5), (2.5, 0), attachment=first_attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 26),
        leader_target_mm=(2.5, 20),
        leader_attachment=last_attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
        version=10,
    )
    current = next(item for item in services.kernel.sketches if item.sketch_id == first.sketch_id)
    points = (
        (source.points_mm[0], *reversed(source.points_mm[1:]))
        if stable_anchor
        else (*source.points_mm[1:], source.points_mm[0])
    )
    changed = replace(source, points_mm=points)
    state = replace(current, entities=(changed,)).to_state_mapping()
    mapping = PolylineTopologyMap(
        source.entity_id, (0, 3, 2, 1) if stable_anchor else (3, 0, 1, 2), 4, True
    )
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=58)
    assert loaded.document.command_count == count
    if not stable_anchor:
        with pytest.raises(ValidationError):
            loaded.bus.execute("drawing.sketch.revise", params, "local", version=59)
        assert services.kernel.drawing_datum_identifiers == (datum,)
        assert services.kernel.drawing_tolerance_frames == (frame,)
        return
    replacement_current = next(
        item for item in services.kernel.sketches if item.sketch_id == other.sketch_id
    )
    distorted = replace(replacement, points_mm=((30, 0), (40, 0), (42, 10), (30, 10)))
    distorted_state = replace(replacement_current, entities=(distorted,)).to_state_mapping()
    changed_other = {
        "sketch_id": replacement_current.sketch_id,
        "base_state_sha256": replacement_current.local_state_digest(),
        "entities": distorted_state["entities"],
        "constraints": distorted_state["constraints"],
    }
    source_revision = {
        "sketch_id": current.sketch_id,
        "base_state_sha256": current.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {**params, "revisions": [source_revision, changed_other]},
            "local",
            version=59,
        )
    assert loaded.document.command_count == count
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert next(s for s in services.kernel.sketches if s.sketch_id == last.sketch_id).entities == (
        target,
    )
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=59)
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx((2.5, 0))
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.associative_arrays == (array,)
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)
    assert next(s for s in services.kernel.sketches if s.sketch_id == last.sketch_id).entities == (
        target,
    )
    path = tmp_path / "array-replacement-reorder.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (frame,)
    assert reopened.kernel.associative_arrays == (array,)
    if relation is not None:
        assert reopened.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated,)


def test_array_extra_output_keeps_attached_datum_on_source_reorder(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    member = replace(source, entity_id=uuid4().hex, points_mm=((5, 0), (15, 0), (15, 10), (5, 10)))
    extra_source = LineEntity(uuid4().hex, (30, 0), (40, 0))
    extra_target = LineEntity(uuid4().hex, (5, 0), (15, 0))
    sketches = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
        for entity in (source, member, extra_source, extra_target)
    )
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(
        ArrayEntityRef(sketch.sketch_id, sketch.entities[0].entity_id) for sketch in sketches
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketches[0].frame,
        1,
        2,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1),),
        extra_outputs=(ArrayExtraOutput(refs[2], refs[3], refs[0], 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local", version=14)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 5),
        (5, 0),
        attachment=DatumAttachment(
            sketches[3].sketch_id, SketchGeometryReference(extra_target.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = next(s for s in services.kernel.sketches if s.sketch_id == sketches[0].sketch_id)
    changed = replace(source, points_mm=(source.points_mm[0], *reversed(source.points_mm[1:])))
    state = replace(current, entities=(changed,)).to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=59)
    assert loaded.document.command_count == count
    changed_extra = replace(extra_source, end_mm=(42, 0))
    extra_state = replace(sketches[2], entities=(changed_extra,)).to_state_mapping()
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                **params,
                "revisions": [
                    *params["revisions"],
                    {
                        "sketch_id": sketches[2].sketch_id,
                        "base_state_sha256": sketches[2].local_state_digest(),
                        "entities": extra_state["entities"],
                        "constraints": extra_state["constraints"],
                    },
                ],
            },
            "local",
            version=60,
        )
    assert loaded.document.command_count == count
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=60)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert next(
        s for s in services.kernel.sketches if s.sketch_id == sketches[3].sketch_id
    ).entities == (extra_target,)
    path = tmp_path / "extra-output-reorder.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("independent", [False, True])
def test_array_extra_output_reorder_rebinds_attached_datum(
    tmp_path: Path, independent: bool
) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    member = replace(
        source, entity_id=uuid4().hex, points_mm=tuple((x + 5, y) for x, y in source.points_mm)
    )
    extra = replace(
        source, entity_id=uuid4().hex, points_mm=tuple((x + 5, y + 20) for x, y in source.points_mm)
    )
    extra_source = replace(
        source, entity_id=uuid4().hex, points_mm=tuple((x + 30, y) for x, y in source.points_mm)
    )
    sketches = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,))
        for item in (source, member, extra, extra_source)
    )
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(
        ArrayEntityRef(sketch.sketch_id, sketch.entities[0].entity_id) for sketch in sketches
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketches[0].frame,
        1,
        2,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1),),
        extra_outputs=(
            ArrayExtraOutput(refs[3] if independent else refs[0], refs[2], refs[0], 0, 1, (0, -20)),
        ),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local", version=14)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (8, 25),
        (7.5, 20),
        attachment=DatumAttachment(
            sketches[2].sketch_id, SketchGeometryReference(extra.entity_id, "segment", 0), 0.25, 4
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    original = extra_source if independent else source
    current = next(
        s
        for s in services.kernel.sketches
        if s.sketch_id == sketches[3 if independent else 0].sketch_id
    )
    changed = replace(
        original, points_mm=(original.points_mm[0], *reversed(original.points_mm[1:]))
    )
    state = replace(current, entities=(changed,)).to_state_mapping()
    mapping = PolylineTopologyMap(original.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": current.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise", params, "local", version=61 if independent else 60
        )
    assert loaded.document.command_count == count
    false_mapping = PolylineTopologyMap(original.entity_id, (0, 1, 2, 3), 4, True)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                **params,
                "polyline_topology_maps": [
                    {"sketch_id": current.sketch_id, "mapping": false_mapping.to_mapping()}
                ],
            },
            "local",
            version=62 if independent else 61,
        )
    assert loaded.document.command_count == count
    assert services.kernel.drawing_datum_identifiers == (datum,)
    if independent:
        shifted_first = replace(
            original, points_mm=(*original.points_mm[1:], original.points_mm[0])
        )
        shifted_state = replace(current, entities=(shifted_first,)).to_state_mapping()
        shifted_map = PolylineTopologyMap(original.entity_id, (3, 0, 1, 2), 4, True)
        with pytest.raises(ValidationError):
            loaded.bus.execute(
                "drawing.sketch.revise",
                {
                    "revisions": [
                        {
                            "sketch_id": current.sketch_id,
                            "base_state_sha256": current.local_state_digest(),
                            "entities": shifted_state["entities"],
                            "constraints": shifted_state["constraints"],
                        }
                    ],
                    "polyline_topology_maps": [
                        {"sketch_id": current.sketch_id, "mapping": shifted_map.to_mapping()}
                    ],
                },
                "local",
                version=62,
            )
        assert loaded.document.command_count == count
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=62 if independent else 61)
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    path = tmp_path / "extra-output-rebind.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated,)


@pytest.mark.parametrize("locked_kind", ["text", "raster"])
def test_mixed_tolerance_move_locked_auxiliary_rolls_back(locked_kind: str) -> None:
    import base64
    import struct
    import zlib

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch_layers import SketchLayer

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("LOCK"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 5))
    note = DrawingText(
        uuid4().hex, "note", (0, 0), layer_name="LOCK" if locked_kind == "text" else "0"
    )
    raster = DrawingRaster(
        uuid4().hex,
        base64.b64encode(png).decode("ascii"),
        (0, 10),
        1,
        1,
        layer_name="LOCK" if locked_kind == "raster" else "0",
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    loaded.bus.execute("drawing.text.add", note.to_mapping(), "local")
    loaded.bus.execute("drawing.raster.add", raster.to_mapping(version=2), "local", version=2)
    locked = layers.replace(replace(layers.get("LOCK"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    before = loaded.document.commands
    with pytest.raises(ValidationError):
        app.move_tolerance_selection(
            services,
            loaded,
            (),
            (frame.frame_id,),
            (),
            (),
            (5, 3),
            session_identity=0,
            text_ids=(note.text_id,),
            raster_ids=(raster.image_id,),
        )
    assert loaded.document.commands == before
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert services.kernel.drawing_texts == (note,) and services.kernel.drawing_rasters == (raster,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_auto_route_requires_new_tolerance_command_version(owner: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (10, 10),
            (0, 0),
            attachment=attachment,
            leader_offsets=((-10, -5),),
            leader_auto_normal=True,
            leader_auto_route=True,
        )
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 10),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            leader_offsets=((-10, -5),),
            leader_auto_normal=True,
            leader_auto_route=True,
        )
        params = {"add_frames": [item.to_mapping()]}
    with pytest.raises(ValidationError, match="版本 22"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=21)
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=22)
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert items == (item,)


@pytest.mark.parametrize("version", [21, 22])
def test_manual_normal_leader_vertices_keep_legacy_semantics(version: int) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-5, -2), (-10, -5)),
        leader_auto_normal=True,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=version
    )
    state = replace(sketch, entities=(replace(line, end_mm=(0, 20)),)).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    changed = services.kernel.drawing_datum_identifiers[0]
    assert not changed.leader_auto_route
    assert len(changed.leader_offsets) == 2
    assert changed.leader_offsets[0] == datum.leader_offsets[0]
    assert changed.leader_offsets[-1] != datum.leader_offsets[-1]


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_auto_route_rejects_target_moving_onto_fixed_box_waypoint(owner: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (10, 10),
            (0, 0),
            attachment=attachment,
            leader_offsets=((-10, -5),),
            leader_auto_normal=True,
            leader_auto_route=True,
        )
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 10),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            leader_offsets=((-10, -5),),
            leader_auto_normal=True,
            leader_auto_route=True,
        )
        params = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params, "local")
    state = replace(
        sketch, entities=(replace(line, start_mm=(0, 5), end_mm=(20, 5)),)
    ).to_state_mapping()
    revision = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ]
    }
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="引线"):
        loaded.bus.execute("drawing.sketch.revise", revision, "local")
    assert services.kernel.sketches == (sketch,)
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert items == (item,)
    assert loaded.document.command_count == count


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_auto_route_requires_tolerance_command_version_22(owner: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    surface = SurfaceIndication((3, 8), (8, 8), 0.5, ((0, 5),), auto_normal=True, auto_route=True)
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex, "A", (10, 10), (0, 0), attachment=attachment, surface_indication=surface
        )
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 10),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            surface_indication=surface,
        )
        params = {"add_frames": [item.to_mapping()]}
    with pytest.raises(ValidationError, match="版本 22"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=21)
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=22)
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert items == (item,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_auto_route_rejects_crossing_arrow_and_rolls_back(owner: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    surface = SurfaceIndication(
        (-3, 0), (-8, 0), 0.5, ((0, 5), (-3, 5)), auto_normal=True, auto_route=True
    )
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex, "A", (10, 10), (0, 0), attachment=attachment, surface_indication=surface
        )
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 10),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            surface_indication=surface,
        )
        params = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params, "local")
    state = replace(sketch, entities=(replace(line, end_mm=(0, 20)),)).to_state_mapping()
    revision = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ]
    }
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="引线"):
        loaded.bus.execute("drawing.sketch.revise", revision, "local")
    assert services.kernel.sketches == (sketch,)
    items = (
        services.kernel.drawing_datum_identifiers
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames
    )
    assert items == (item,)
    assert loaded.document.command_count == count


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_version_22_automatic_route_replays_legacy_corner(
    tmp_path: Path, owner: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import math

    import mycad.geom.kernel as kernel_module
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    offsets = ((-8.0, 0.0), (-10.0, 2 + math.sqrt(50)))
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (10, -2),
            (0, 0),
            attachment=attachment,
            leader_offsets=offsets,
            leader_auto_normal=True,
            leader_auto_route=True,
        )
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, -2),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            leader_offsets=offsets,
            leader_auto_normal=True,
            leader_auto_route=True,
        )
        params = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=22)
    state = replace(sketch, entities=(replace(line, end_mm=(20, -20)),)).to_state_mapping()
    revision = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ]
    }

    def legacy_route(
        position: tuple[float, float],
        offsets: tuple[tuple[float, float], ...],
        normal: tuple[float, float],
        target: tuple[float, float],
        *,
        avoid_crossing: bool = False,
    ) -> tuple[tuple[float, float], ...]:
        del target, avoid_crossing
        first = (position[0] + offsets[0][0], position[1] + offsets[0][1])
        corner = (first[0], normal[1])
        return tuple((x - position[0], y - position[1]) for x, y in (first, corner, normal))

    with monkeypatch.context() as patch:
        patch.setattr(kernel_module, "reroute_orthogonal_leader", legacy_route)
        loaded.bus.execute("drawing.sketch.revise", revision, "local", version=56)
        old_result = (
            services.kernel.drawing_datum_identifiers[0]
            if owner == "datum"
            else services.kernel.drawing_tolerance_frames[0]
        )
    loaded.bus.undo_operation()
    loaded.bus.redo_operation()
    replayed = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert replayed == old_result

    path = tmp_path / "legacy-route.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    restored = (
        reopened.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames[0]
    )
    assert restored == old_result


@pytest.mark.parametrize("owner", ["datum", "frame", "surface"])
def test_avoid_crossing_policy_requires_tolerance_version_23(owner: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    surface = SurfaceIndication(
        (3, 8),
        (8, 8),
        0.5,
        ((0, 5),),
        auto_normal=True,
        auto_route=True,
        route_avoid_crossing=True,
    )
    if owner in ("datum", "surface"):
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (10, 10),
            (0, 0),
            attachment=attachment,
            leader_offsets=((-10, -5),),
            leader_auto_normal=owner == "datum",
            leader_auto_route=owner == "datum",
            route_avoid_crossing=owner == "datum",
            surface_indication=surface if owner == "surface" else None,
        )
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 10),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            leader_offsets=((-10, -5),),
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
        )
        params = {"add_frames": [item.to_mapping()]}
    with pytest.raises(ValidationError, match="版本 23"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=22)
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=23)
    items = (
        services.kernel.drawing_tolerance_frames
        if owner == "frame"
        else services.kernel.drawing_datum_identifiers
    )
    assert items == (item,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("version", [22, 23])
def test_surface_route_policy_preserves_versioned_replay(
    tmp_path: Path, owner: str, version: int
) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    surface = SurfaceIndication(
        (2, -2),
        (7, -2),
        0.5,
        ((0, math.sqrt(50)),),
        auto_normal=True,
        auto_route=True,
        route_avoid_crossing=version == 23,
    )
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex, "A", (10, 10), (0, 0), attachment=attachment, surface_indication=surface
        )
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 10),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            surface_indication=surface,
        )
        params = {"add_frames": [item.to_mapping()]}
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=version)
    state = replace(sketch, entities=(replace(line, end_mm=(20, -20)),)).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=56,
    )
    result = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert result.surface_indication is not None
    offsets = result.surface_indication.leader_offsets_mm
    assert offsets[0] == pytest.approx((5, 5))
    assert offsets[1] == pytest.approx((2, 5) if version == 22 else (5, -2))
    loaded.bus.undo_operation()
    loaded.bus.redo_operation()
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == result
    path = tmp_path / "surface-policy.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert (
        reopened.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames[0]
    ) == result


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("move_target", [False, True])
def test_mixed_move_preserves_automatic_route(owner: str, move_target: bool) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    other = LineEntity(uuid4().hex, (0, 40), (20, 40))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target, other))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(target.entity_id, "geometry"), 0.5
    )
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (20, 5),
            (10, 0),
            attachment=attachment,
            leader_offsets=((-10, 0),),
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
        )
        params = {"add_datums": [item.to_mapping()]}
        frame_ids, datum_ids = (), (item.datum_id,)
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (20, 5),
            leader_target_mm=(10, 0),
            leader_attachment=attachment,
            leader_offsets=((-10, 0),),
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
        )
        params = {"add_frames": [item.to_mapping()]}
        frame_ids, datum_ids = (item.frame_id,), ()
    loaded.bus.execute("drawing.tolerance.batch", params, "local")
    app.move_tolerance_selection(
        services,
        loaded,
        (target.entity_id if move_target else other.entity_id,),
        frame_ids,
        datum_ids,
        (),
        (4, 3),
        session_identity=0,
    )
    moved = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert moved.leader_auto_route and moved.route_avoid_crossing
    vertex = (
        moved.position_mm[0] + moved.leader_offsets[-1][0],
        moved.position_mm[1] + moved.leader_offsets[-1][1],
    )
    assert vertex == pytest.approx((14, 8) if move_target else (10, 5))
    loaded.bus.undo_operation()
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == item
    loaded.bus.redo_operation()
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == moved


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("version", [23, 24])
def test_auto_route_rechecks_arrow_when_target_moves_but_vertex_is_fixed(
    tmp_path: Path, owner: str, version: int
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    offsets = ((-4, 0), (-4, 3), (-10, 3))
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (10, 2),
            (0, 0),
            attachment=attachment,
            leader_offsets=offsets,
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
            route_track_target=version == 24,
        )
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 2),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            leader_offsets=offsets,
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
            route_track_target=version == 24,
        )
        params = {"add_frames": [item.to_mapping()]}
    if version == 24:
        with pytest.raises(ValidationError, match="版本 24"):
            loaded.bus.execute("drawing.tolerance.batch", params, "local", version=23)
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=version)
    state = replace(
        sketch, entities=(replace(line, start_mm=(5, 5), end_mm=(5, 25)),)
    ).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=56,
    )
    result = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    target = result.target_mm if isinstance(result, DatumIdentifier) else result.leader_target_mm
    assert target == pytest.approx((5, 5))
    assert result.leader_offsets[-1] == pytest.approx(offsets[-1])
    assert result.leader_offsets == (((-4, 0), (-10, 0), (-10, 3)) if version == 24 else offsets)
    loaded.bus.undo_operation()
    loaded.bus.redo_operation()
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == result

    path = tmp_path / "fixed-normal-route.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert (
        reopened.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames[0]
    ) == result


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_mixed_move_of_target_and_auto_route_accepts_transient_overlap(
    tmp_path: Path, owner: str
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (20, 5),
            (10, 0),
            attachment=attachment,
            leader_offsets=((-10, 0),),
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
            route_track_target=True,
            route_algorithm_version=2,
        )
        params = {"add_datums": [item.to_mapping()]}
        frame_ids, datum_ids = (), (item.datum_id,)
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (20, 5),
            leader_target_mm=(10, 0),
            leader_attachment=attachment,
            leader_offsets=((-10, 0),),
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
            route_track_target=True,
            route_algorithm_version=2,
        )
        params = {"add_frames": [item.to_mapping()]}
        frame_ids, datum_ids = (item.frame_id,), ()
    loaded.bus.execute("drawing.tolerance.batch", params, "local")
    app.move_tolerance_selection(
        services,
        loaded,
        (line.entity_id,),
        frame_ids,
        datum_ids,
        (),
        (0, 5),
        session_identity=0,
    )
    moved = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    assert moved.position_mm == pytest.approx((20, 10))
    target = moved.target_mm if isinstance(moved, DatumIdentifier) else moved.leader_target_mm
    assert target == pytest.approx((10, 5))
    assert moved.leader_offsets == item.leader_offsets
    assert moved.route_track_target
    loaded.bus.undo_operation()
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == item
    loaded.bus.redo_operation()
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == moved

    path = tmp_path / "mixed-translation.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert (
        reopened.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames[0]
    ) == moved


def test_mixed_move_does_not_bypass_unselected_annotation_protection() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    first = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 5),
        (10, 0),
        attachment=attachment,
        leader_offsets=((-10, 0),),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
    )
    second = replace(first, datum_id=uuid4().hex, label="B")
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [first.to_mapping(), second.to_mapping()]},
        "local",
    )
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="引线"):
        app.move_tolerance_selection(
            services,
            loaded,
            (line.entity_id,),
            (),
            (first.datum_id,),
            (),
            (0, 5),
            session_identity=0,
        )
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_datum_identifiers == (first, second)
    assert loaded.document.command_count == count


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("version", [24, 25])
def test_auto_route_rechecks_box_segment_when_target_moves(
    tmp_path: Path, owner: str, version: int
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (5, 0), (25, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    offsets = ((3, 0), (3, 3), (5, 3))
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (0, 2),
            (5, 0),
            attachment=attachment,
            leader_offsets=offsets,
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
            route_track_target=True,
            route_algorithm_version=2 if version == 25 else 1,
        )
        params = {"add_datums": [item.to_mapping()]}
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (0, 2),
            leader_target_mm=(5, 0),
            leader_anchor_offset=(0, 1),
            leader_attachment=attachment,
            leader_offsets=offsets,
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
            route_track_target=True,
            route_algorithm_version=2 if version == 25 else 1,
        )
        params = {"add_frames": [item.to_mapping()]}
    if version == 25:
        with pytest.raises(ValidationError, match="版本 25"):
            loaded.bus.execute("drawing.tolerance.batch", params, "local", version=24)
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=version)
    state = replace(
        sketch, entities=(replace(line, start_mm=(2, 1), end_mm=(6, -2)),)
    ).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=56,
    )
    result = (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    )
    # The old box-to-first segment crosses the new arrow at x=2.75, y=2.
    # A safe route leaves the box vertically before reaching the normal vertex.
    assert result.leader_offsets[0] == pytest.approx((0, 3) if version == 25 else (3, 0))
    assert result.leader_offsets[-1] == pytest.approx((5, 3))

    loaded.bus.undo_operation()
    loaded.bus.redo_operation()
    assert (
        services.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else services.kernel.drawing_tolerance_frames[0]
    ) == result
    path = tmp_path / "box-guard.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert (
        reopened.kernel.drawing_datum_identifiers[0]
        if owner == "datum"
        else reopened.kernel.drawing_tolerance_frames[0]
    ) == result


def test_datum_recorded_box_size_requires_version_26_and_replays(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    datum = DatumIdentifier(
        uuid4().hex, "A", (2, 3), (10, 0), layout_mode="shared", box_size_mm=(8, 5)
    )
    params = {"add_datums": [datum.to_mapping()]}
    with pytest.raises(ValidationError, match="版本 26"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=25)
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=26)
    loaded.bus.undo_operation()
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    path = tmp_path / "datum-box-size.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)


def test_datum_box_aware_route_replays_actual_clipped_geometry(tmp_path: Path) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_geometry import datum_leader_path
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    old_target = (2.0, 2.0 + math.sqrt(146))
    line = LineEntity(uuid4().hex, old_target, (22, old_target[1]))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 0),
        old_target,
        attachment=attachment,
        leader_offsets=((10, 15), (10, 2), (2, 2)),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=3,
        layout_mode="shared",
        box_size_mm=(5.212759544541193, 5),
    )
    params = {"add_datums": [datum.to_mapping()]}
    with pytest.raises(ValidationError, match="版本 26"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=25)
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=26)
    state = replace(
        sketch, entities=(replace(line, start_mm=(13, 7), end_mm=(18, -4)),)
    ).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=56,
    )
    result = services.kernel.drawing_datum_identifiers[0]
    assert datum.box_size_mm is not None
    path = datum_leader_path(
        (0, 0, datum.box_size_mm[0], -datum.box_size_mm[1]), result.target_mm, result.leader_offsets
    )
    assert path[-2] == pytest.approx((2, 2))
    assert 0 <= path[0][0] <= datum.box_size_mm[0]
    assert path[0][1] == pytest.approx(0)
    assert path[1] == pytest.approx((2, 2))
    loaded.bus.undo_operation()
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (result,)
    path_file = tmp_path / "box-aware.my2d"
    save_document(loaded.document, path_file)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path_file)
    assert reopened.kernel.drawing_datum_identifiers == (result,)


def test_datum_box_aware_route_rolls_back_if_arrow_would_cross_box() -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    old_target = (-7.0, -3.0 + math.sqrt(272))
    line = LineEntity(uuid4().hex, old_target, (13, old_target[1]))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 0),
        old_target,
        attachment=attachment,
        leader_offsets=((2.6063797722705964, -3), (-7, -3)),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=3,
        layout_mode="shared",
        box_size_mm=(5.212759544541193, 5),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=26
    )
    state = replace(
        sketch, entities=(replace(line, start_mm=(9, 1), end_mm=(13, -15)),)
    ).to_state_mapping()
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="框"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
            version=56,
        )
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert loaded.document.command_count == count


@pytest.mark.parametrize("algorithm", [3, 4])
def test_mixed_move_box_aware_datum_uses_actual_clipped_box(algorithm: int) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_geometry import datum_leader_path, reroute_leader_around_box
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (13, 7), (18, -4))
    other = LineEntity(uuid4().hex, (0, 40), (20, 40))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, other))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (-4, -3),
        (13, 7),
        attachment=attachment,
        leader_offsets=reroute_leader_around_box(
            (-4, -3),
            ((10, 15), (6, 5)),
            (2, 2),
            (13, 7),
            (-4, -3, 1.212759544541193, -8),
            orthogonal_box_side=algorithm == 4,
        ),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=algorithm,
        layout_mode="shared",
        box_size_mm=(5.212759544541193, 5),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()]},
        "local",
        version=26 if algorithm == 3 else 27,
    )
    app.move_tolerance_selection(
        services, loaded, (other.entity_id,), (), (datum.datum_id,), (), (4, 3), session_identity=0
    )
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.position_mm == pytest.approx((0, 0))
    assert moved.leader_offsets[-1] == pytest.approx((2, 2))
    path = datum_leader_path((0, 0, 5.212759544541193, -5), moved.target_mm, moved.leader_offsets)
    if algorithm == 3:
        assert path[0][1] == pytest.approx(0)
        assert path[1] == pytest.approx((2, 2))
    else:
        assert all(
            abs(a[0] - b[0]) <= 1e-9 or abs(a[1] - b[1]) <= 1e-9
            for a, b in zip(path[:-2], path[1:-1], strict=True)
        )
    loaded.bus.undo_operation()
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (moved,)


def test_style_change_updates_recorded_datum_box_atomically(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("custom", "自定义", height_mm=3.5)
    styles = TextStyleTable((TextStyle(), style))
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local", version=1)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 3),
        (30, 0),
        text_style_id="custom",
        layout_mode="shared",
        box_size_mm=(5.3, 5),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=26
    )
    changed_style = replace(style, height_mm=7)
    changed_styles = TextStyleTable((TextStyle(), changed_style))
    changed_datum = replace(datum, box_size_mm=(10.6, 10))
    before = loaded.document.command_count
    with pytest.raises(ValidationError, match="基准框"):
        loaded.bus.execute(
            "drawing.text_styles.set", changed_styles.to_mapping(), "local", version=1
        )
    assert loaded.document.command_count == before
    payload = {**changed_styles.to_mapping(), "datum_updates": [changed_datum.to_mapping()]}
    loaded.bus.execute("drawing.text_styles.set", payload, "local", version=2)
    assert services.kernel.drawing_text_styles == changed_styles
    assert services.kernel.drawing_datum_identifiers == (changed_datum,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_text_styles == styles
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    path = tmp_path / "styled-datum-box.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_text_styles == changed_styles
    assert reopened.kernel.drawing_datum_identifiers == (changed_datum,)


@pytest.mark.parametrize("case", ["missing", "duplicate", "unrelated", "text_batch"])
def test_style_box_update_rejects_incomplete_or_unrelated_changes(case: str) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("custom", "自定义", height_mm=3.5)
    styles = TextStyleTable((TextStyle(), style))
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local", version=1)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 3),
        (30, 0),
        text_style_id="custom",
        layout_mode="shared",
        box_size_mm=(5.3, 5),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=26
    )
    changed_styles = TextStyleTable((TextStyle(), replace(style, height_mm=7)))
    update = replace(datum, box_size_mm=(10.6, 10))
    payload: dict[str, object] = dict(changed_styles.to_mapping())
    if case == "duplicate":
        payload["datum_updates"] = [update.to_mapping(), update.to_mapping()]
    elif case == "unrelated":
        payload["datum_updates"] = [replace(update, label="B").to_mapping()]
    before = loaded.document.command_count
    with pytest.raises(ValidationError, match="基准框"):
        if case == "text_batch":
            loaded.bus.execute(
                "drawing.text.batch", {"styles": changed_styles.to_mapping()}, "local"
            )
        else:
            loaded.bus.execute("drawing.text_styles.set", payload, "local", version=2)
    assert loaded.document.command_count == before
    assert services.kernel.drawing_text_styles == styles
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_style_name_only_change_does_not_require_datum_box_update() -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("custom", "原名")
    loaded.bus.execute(
        "drawing.text_styles.set",
        TextStyleTable((TextStyle(), style)).to_mapping(),
        "local",
        version=1,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 3),
        (30, 0),
        text_style_id="custom",
        layout_mode="shared",
        box_size_mm=(5.3, 5),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=26
    )
    changed = TextStyleTable((TextStyle(), replace(style, name="新名")))
    loaded.bus.execute("drawing.text_styles.set", changed.to_mapping(), "local", version=2)
    assert services.kernel.drawing_text_styles == changed
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_shared_style_update_rejects_box_that_covers_attached_target() -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    style = TextStyle("custom", "基准", height_mm=3.5)
    styles = TextStyleTable((TextStyle(), style))
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local", version=1)
    line = LineEntity(uuid4().hex, (10, -3), (10, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 0),
        (10, -3),
        text_style_id="custom",
        layout_mode="shared",
        box_size_mm=(5, 5),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((7, -3),),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=3,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=26
    )
    next_styles = TextStyleTable((TextStyle(), replace(style, height_mm=14)))
    invalid = replace(datum, box_size_mm=(20, 20))
    before = loaded.document.command_count
    with pytest.raises(ValidationError, match="框"):
        loaded.bus.execute(
            "drawing.text_styles.set",
            {**next_styles.to_mapping(), "datum_updates": [invalid.to_mapping()]},
            "local",
            version=2,
        )
    assert loaded.document.command_count == before
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_text_styles == styles


def test_box_aware_datum_rejects_arrow_crossing_box_on_creation() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (3, -10), (13, -10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 0),
        (3, -10),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((3, 5),),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=3,
        layout_mode="shared",
        box_size_mm=(6, 5),
    )
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="框"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=26
        )
    assert not services.kernel.drawing_datum_identifiers
    assert loaded.document.command_count == count


def test_strict_datum_route_is_versioned_and_rejects_diagonal_box_segment() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (13, 7), (18, -4))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 0),
        (13, 7),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((2, -2.5), (2, 2)),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=4,
        layout_mode="shared",
        box_size_mm=(5.212759544541193, 5),
    )
    params = {"add_datums": [datum.to_mapping()]}
    with pytest.raises(ValidationError, match="版本 27"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=26)
    with pytest.raises(ValidationError, match="正交"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=27)
    assert not services.kernel.drawing_datum_identifiers


@pytest.mark.parametrize("algorithm,command_version", [(3, 26), (4, 27)])
def test_versioned_datum_reroute_preserves_replay_semantics(
    tmp_path: Path, algorithm: int, command_version: int
) -> None:
    import math

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_geometry import datum_leader_path, reroute_leader_around_box
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    target = (2.0, 2.0 + math.sqrt(146))
    line = LineEntity(uuid4().hex, target, (22, target[1]))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    box = (0.0, 0.0, 5.212759544541193, -5.0)
    normal = (2.0, 2.0)
    initial = reroute_leader_around_box(
        (0, 0),
        ((10, 15), normal),
        normal,
        target,
        box,
        orthogonal_box_side=algorithm == 4,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 0),
        target,
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=initial,
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=algorithm,
        layout_mode="shared",
        box_size_mm=(box[2], -box[3]),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()]},
        "local",
        version=command_version,
    )
    state = replace(
        sketch, entities=(replace(line, start_mm=(13, 7), end_mm=(18, -4)),)
    ).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=56,
    )
    result = services.kernel.drawing_datum_identifiers[0]
    path = datum_leader_path(box, result.target_mm, result.leader_offsets)
    if algorithm == 4:
        assert all(
            abs(a[0] - b[0]) <= 1e-9 or abs(a[1] - b[1]) <= 1e-9
            for a, b in zip(path[:-2], path[1:-1], strict=True)
        )
    else:
        assert len(result.leader_offsets) == 2
        assert result.leader_offsets[0] == pytest.approx((2.0, -2.5))
        assert result.leader_offsets[1] == pytest.approx((2.0, 2.0))
    loaded.bus.undo_operation()
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (result,)
    output = tmp_path / f"route-{algorithm}.my2d"
    save_document(loaded.document, output)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, output)
    assert reopened.kernel.drawing_datum_identifiers == (result,)


def test_strict_box_aware_datum_moves_with_attached_target_atomically(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_geometry import reroute_leader_around_box
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (13, 7), (18, -4))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    box = (0.0, 0.0, 5.212759544541193, -5.0)
    offsets = reroute_leader_around_box(
        (0, 0), ((10, 15), (2, 2)), (2, 2), (13, 7), box, orthogonal_box_side=True
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 0),
        (13, 7),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=offsets,
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=4,
        layout_mode="shared",
        box_size_mm=(box[2], -box[3]),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=27
    )
    app.move_tolerance_selection(
        services, loaded, (line.entity_id,), (), (datum.datum_id,), (), (4, 3), session_identity=0
    )
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.position_mm == pytest.approx((4, 3))
    assert moved.target_mm == pytest.approx((17, 10))
    assert moved.leader_offsets == datum.leader_offsets and moved.route_algorithm_version == 4
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (moved,)
    output = tmp_path / "strict-mixed-move.my2d"
    save_document(loaded.document, output)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, output)
    assert reopened.kernel.drawing_datum_identifiers == (moved,)


@pytest.mark.parametrize("has_ids", [False, True])
def test_chained_array_reorder_rebinds_nested_annotations_and_replays(
    tmp_path: Path, has_ids: bool
) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(uuid4().hex, ((0, y), (10, y), (10, y + 10))) for y in (0, 20, 40, 60)
    )
    if has_ids:
        entities = tuple(
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 3))
            for item in entities
        )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target in zip(refs[:-1], refs[1:], strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0),),
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 45),
        (2.5, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[2].entity_id, "segment", 0), 0.25, 2
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 66),
        leader_target_mm=(2.5, 60),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 2
        ),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reversed_source = replace(
        entities[0],
        points_mm=tuple(reversed(entities[0].points_mm)),
        point_ids=tuple(reversed(entities[0].point_ids)),
    )
    state = replace(sketch, entities=(reversed_source, *entities[1:])).to_state_mapping()
    mapping = PolylineTopologyMap(entities[0].entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    inferred, _base_rebind, version = app.exact_attached_polyline_reorder_maps(
        services, (sketch,), (replace(sketch, entities=(reversed_source, *entities[1:])),)
    )
    assert inferred == tuple(params["polyline_topology_maps"])
    assert version == 66
    with pytest.raises(ValidationError, match="链式|关联"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=65)
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=66)
    after_datum, after_frame = (
        services.kernel.drawing_datum_identifiers[0],
        services.kernel.drawing_tolerance_frames[0],
    )
    if has_ids:
        revised_entities = services.kernel.sketches[0].entities
        for before, after in zip(entities, revised_entities, strict=True):
            assert isinstance(after, PolylineEntity)
            assert after.point_ids == tuple(reversed(before.point_ids))
    assert after_datum.attachment is not None and after_datum.attachment.reference.index == 1
    assert (
        after_frame.leader_attachment is not None
        and after_frame.leader_attachment.reference.index == 1
    )
    assert after_datum.target_mm == pytest.approx(datum.target_mm)
    assert after_frame.leader_target_mm == pytest.approx(frame.leader_target_mm)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (after_datum,)
    output = tmp_path / "chain-reorder.my2d"
    save_document(loaded.document, output)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, output)
    assert reopened.kernel.drawing_datum_identifiers == (after_datum,)
    assert reopened.kernel.drawing_tolerance_frames == (after_frame,)


@pytest.mark.parametrize("case", ["locked", "mapping"])
def test_chained_array_reorder_rejects_unsafe_changes_atomically(case: str) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    has_ids = False
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(uuid4().hex, ((0, y), (10, y), (10, y + 10))) for y in (0, 20, 40, 60)
    )
    if has_ids:
        entities = tuple(
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 3))
            for item in entities
        )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target in zip(refs[:-1], refs[1:], strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0),),
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 45),
        (2.5, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[2].entity_id, "segment", 0), 0.25, 2
        ),
    )
    layers = services.kernel.drawing_layers.add(SketchLayer("CHAIN"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 66),
        leader_target_mm=(2.5, 60),
        layer_name="CHAIN",
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 2
        ),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reversed_source = replace(
        entities[0],
        points_mm=tuple(reversed(entities[0].points_mm)),
        point_ids=tuple(reversed(entities[0].point_ids)),
    )
    state = replace(sketch, entities=(reversed_source, *entities[1:])).to_state_mapping()
    mapping = PolylineTopologyMap(entities[0].entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    if case == "locked":
        locked = replace(
            layers,
            layers=tuple(
                replace(layer, locked=True) if layer.name == "CHAIN" else layer
                for layer in layers.layers
            ),
        )
        loaded.bus.execute(
            "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    else:
        wrong = PolylineTopologyMap(entities[0].entity_id, (1, 2, 0), 3, False)
        params["polyline_topology_maps"] = [
            {"sketch_id": sketch.sketch_id, "mapping": wrong.to_mapping()}
        ]
    before_sketches = services.kernel.sketches
    params["revisions"][0]["base_state_sha256"] = before_sketches[0].local_state_digest()
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="锁定" if case == "locked" else "映射|重排|拓扑"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=66)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before_sketches
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


@pytest.mark.parametrize("bulge", [0.0, 0.3])
@pytest.mark.parametrize("has_ids", [False, True])
def test_chained_rotated_arrays_reorder_with_stable_anchors_replays(
    tmp_path: Path, has_ids: bool, bulge: float
) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        closed=True,
        bulges=(bulge, 0, 0, 0) if bulge else (),
    )
    entities = [first]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    if has_ids:
        entities = [
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 4))
            for item in entities
        ]
        first = entities[0]
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0, rotation_deg=angle),),
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "segment", 1), 0.25, 4
    )
    target = resolve_attachment_local(attachment, {entities[-1].entity_id: entities[-1]})
    assert target is not None
    datum = DatumIdentifier(uuid4().hex, "A", (20, 50), target, attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (25, 50),
        leader_target_mm=target,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reverse = replace(
        first,
        points_mm=(first.points_mm[0], *reversed(first.points_mm[1:])),
        point_ids=(first.point_ids[0], *reversed(first.point_ids[1:])) if has_ids else (),
        bulges=(0, 0, 0, -bulge) if bulge else (),
    )
    revised = replace(sketch, entities=(reverse, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(first.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="关联|重绑定|阵列"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=66)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 67
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=67)
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert updated_frame.leader_attachment is not None
    assert updated_frame.leader_attachment.reference.index == 2
    assert updated_frame.leader_target_mm == pytest.approx(target)
    if has_ids:
        for before, after in zip(entities, services.kernel.sketches[0].entities, strict=True):
            assert isinstance(after, PolylineEntity)
            assert after.point_ids == (before.point_ids[0], *reversed(before.point_ids[1:]))
    assert updated.target_mm == pytest.approx(target)
    assert updated.attachment is not None and updated.attachment.reference.index == 2
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated,)
    path = tmp_path / "rotated-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)


def test_chained_rotated_arrays_reject_moving_anchor_atomically() -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    entities = [first]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0, rotation_deg=angle),),
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "segment", 1), 0.25, 4
    )
    target = resolve_attachment_local(attachment, {entities[-1].entity_id: entities[-1]})
    assert target is not None
    datum = DatumIdentifier(uuid4().hex, "A", (20, 50), target, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    reverse = replace(first, points_mm=(*first.points_mm[-1:], *first.points_mm[:-1]))
    revised = replace(sketch, entities=(reverse, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(first.entity_id, (1, 2, 3, 0), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    count = loaded.document.command_count
    before = services.kernel.sketches
    records, _, _ = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert not records
    for version in (67, 70):
        with pytest.raises(ValidationError, match="阵列|重绑定|映射|拓扑"):
            loaded.bus.execute("drawing.sketch.revise", params, "local", version=version)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_chained_rotated_arrays_reject_locked_attachment_atomically() -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    has_ids = False
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    entities = [first]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    if has_ids:
        entities = [
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 4))
            for item in entities
        ]
        first = entities[0]
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0, rotation_deg=angle),),
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "segment", 1), 0.25, 4
    )
    target = resolve_attachment_local(attachment, {entities[-1].entity_id: entities[-1]})
    assert target is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("ROTATED_CHAIN"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 50), target, attachment=attachment, layer_name="ROTATED_CHAIN"
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    reverse = replace(
        first,
        points_mm=(first.points_mm[0], *reversed(first.points_mm[1:])),
        point_ids=(first.point_ids[0], *reversed(first.point_ids[1:])) if has_ids else (),
    )
    revised = replace(sketch, entities=(reverse, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(first.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "ROTATED_CHAIN" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    before = services.kernel.sketches
    params["revisions"][0]["base_state_sha256"] = before[0].local_state_digest()
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="锁定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=67)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_chained_rotated_arrays_reject_wrong_bulge_atomically() -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    has_ids, bulge = False, 0.3
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        closed=True,
        bulges=(bulge, 0, 0, 0) if bulge else (),
    )
    entities = [first]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    if has_ids:
        entities = [
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 4))
            for item in entities
        ]
        first = entities[0]
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0, rotation_deg=angle),),
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "segment", 1), 0.25, 4
    )
    target = resolve_attachment_local(attachment, {entities[-1].entity_id: entities[-1]})
    assert target is not None
    datum = DatumIdentifier(uuid4().hex, "A", (20, 50), target, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    reverse = replace(
        first,
        points_mm=(first.points_mm[0], *reversed(first.points_mm[1:])),
        point_ids=(first.point_ids[0], *reversed(first.point_ids[1:])) if has_ids else (),
        bulges=(0, 0, 0, bulge) if bulge else (),
    )
    revised = replace(sketch, entities=(reverse, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(first.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    count = loaded.document.command_count
    before = services.kernel.sketches
    with pytest.raises(ValidationError, match="拓扑|映射|线段|重排"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=67)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_chained_rotated_array_with_stable_dynamic_base_replays(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    has_ids, bulge = True, 0.3
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        closed=True,
        bulges=(bulge, 0, 0, 0) if bulge else (),
    )
    entities = [first]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    if has_ids:
        entities = [
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 4))
            for item in entities
        ]
        first = entities[0]
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0, rotation_deg=angle),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "vertex", 0)
            )
            if source == refs[1]
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "segment", 1), 0.25, 4
    )
    target = resolve_attachment_local(attachment, {entities[-1].entity_id: entities[-1]})
    assert target is not None
    datum = DatumIdentifier(uuid4().hex, "A", (20, 50), target, attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (25, 50),
        leader_target_mm=target,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reverse = replace(
        first,
        points_mm=(first.points_mm[0], *reversed(first.points_mm[1:])),
        point_ids=(first.point_ids[0], *reversed(first.point_ids[1:])) if has_ids else (),
        bulges=(0, 0, 0, -bulge) if bulge else (),
    )
    revised = replace(sketch, entities=(reverse, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(first.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="关联|重绑定|阵列"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=67)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 68
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=68)
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert updated_frame.leader_attachment is not None
    assert updated_frame.leader_attachment.reference.index == 2
    assert updated_frame.leader_target_mm == pytest.approx(target)
    if has_ids:
        for before, after in zip(entities, services.kernel.sketches[0].entities, strict=True):
            assert isinstance(after, PolylineEntity)
            assert after.point_ids == (before.point_ids[0], *reversed(before.point_ids[1:]))
    assert updated.target_mm == pytest.approx(target)
    assert updated.attachment is not None and updated.attachment.reference.index == 2
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated,)
    path = tmp_path / "rotated-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)


def test_chained_array_rejects_changed_dynamic_base_atomically() -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    has_ids, bulge = True, 0.3
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        closed=True,
        bulges=(bulge, 0, 0, 0) if bulge else (),
    )
    entities = [first]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    if has_ids:
        entities = [
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 4))
            for item in entities
        ]
        first = entities[0]
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0, rotation_deg=angle),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "vertex", 1)
            )
            if source == refs[1]
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "segment", 1), 0.25, 4
    )
    target = resolve_attachment_local(attachment, {entities[-1].entity_id: entities[-1]})
    assert target is not None
    datum = DatumIdentifier(uuid4().hex, "A", (20, 50), target, attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (25, 50),
        leader_target_mm=target,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reverse = replace(
        first,
        points_mm=(first.points_mm[0], *reversed(first.points_mm[1:])),
        point_ids=(first.point_ids[0], *reversed(first.point_ids[1:])) if has_ids else (),
        bulges=(0, 0, 0, -bulge) if bulge else (),
    )
    revised = replace(sketch, entities=(reverse, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(first.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    count = loaded.document.command_count
    before = services.kernel.sketches
    records, _, _ = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert not records
    for version in (68, 69):
        with pytest.raises(ValidationError, match="基点|关联|重绑定"):
            loaded.bus.execute("drawing.sketch.revise", params, "local", version=version)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_chained_array_stable_dynamic_base_rejects_locked_attachment() -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    has_ids, bulge = True, 0.3
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        closed=True,
        bulges=(bulge, 0, 0, 0) if bulge else (),
    )
    entities = [first]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    if has_ids:
        entities = [
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 4))
            for item in entities
        ]
        first = entities[0]
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0, rotation_deg=angle),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "vertex", 0)
            )
            if source == refs[1]
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "segment", 1), 0.25, 4
    )
    target = resolve_attachment_local(attachment, {entities[-1].entity_id: entities[-1]})
    assert target is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("CHAINBASE"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 50), target, attachment=attachment, layer_name="CHAINBASE"
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (25, 50),
        leader_target_mm=target,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reverse = replace(
        first,
        points_mm=(first.points_mm[0], *reversed(first.points_mm[1:])),
        point_ids=(first.point_ids[0], *reversed(first.point_ids[1:])) if has_ids else (),
        bulges=(0, 0, 0, -bulge) if bulge else (),
    )
    revised = replace(sketch, entities=(reverse, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(first.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "CHAINBASE" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    before = services.kernel.sketches
    params["revisions"][0]["base_state_sha256"] = before[0].local_state_digest()
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="锁定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=68)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_chained_array_with_stable_nonzero_dynamic_base_replays(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    has_ids, bulge = True, 0.3
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        closed=True,
        bulges=(bulge, 0, 0, 0) if bulge else (),
    )
    entities = [first]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    if has_ids:
        entities = [
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 4))
            for item in entities
        ]
        first = entities[0]
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0, rotation_deg=angle),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "vertex", 2)
            )
            if source == refs[1]
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "segment", 1), 0.25, 4
    )
    target = resolve_attachment_local(attachment, {entities[-1].entity_id: entities[-1]})
    assert target is not None
    datum = DatumIdentifier(uuid4().hex, "A", (20, 50), target, attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (25, 50),
        leader_target_mm=target,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reverse = replace(
        first,
        points_mm=(first.points_mm[0], *reversed(first.points_mm[1:])),
        point_ids=(first.point_ids[0], *reversed(first.point_ids[1:])) if has_ids else (),
        bulges=(0, 0, 0, -bulge) if bulge else (),
    )
    revised = replace(sketch, entities=(reverse, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(first.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="关联|重绑定|阵列"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=68)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 69
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=69)
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert updated_frame.leader_attachment is not None
    assert updated_frame.leader_attachment.reference.index == 2
    assert updated_frame.leader_target_mm == pytest.approx(target)
    if has_ids:
        for before, after in zip(entities, services.kernel.sketches[0].entities, strict=True):
            assert isinstance(after, PolylineEntity)
            assert after.point_ids == (before.point_ids[0], *reversed(before.point_ids[1:]))
    assert updated.target_mm == pytest.approx(target)
    assert updated.attachment is not None and updated.attachment.reference.index == 2
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated,)
    path = tmp_path / "rotated-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)


def test_chained_array_stable_nonzero_base_rejects_locked_attachment() -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    has_ids, bulge = True, 0.3
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        closed=True,
        bulges=(bulge, 0, 0, 0) if bulge else (),
    )
    entities = [first]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    if has_ids:
        entities = [
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 4))
            for item in entities
        ]
        first = entities[0]
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0, rotation_deg=angle),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "vertex", 2)
            )
            if source == refs[1]
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "segment", 1), 0.25, 4
    )
    target = resolve_attachment_local(attachment, {entities[-1].entity_id: entities[-1]})
    assert target is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("CHAINBASE"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 50), target, attachment=attachment, layer_name="CHAINBASE"
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (25, 50),
        leader_target_mm=target,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reverse = replace(
        first,
        points_mm=(first.points_mm[0], *reversed(first.points_mm[1:])),
        point_ids=(first.point_ids[0], *reversed(first.point_ids[1:])) if has_ids else (),
        bulges=(0, 0, 0, -bulge) if bulge else (),
    )
    revised = replace(sketch, entities=(reverse, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(first.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "CHAINBASE" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    before = services.kernel.sketches
    params["revisions"][0]["base_state_sha256"] = before[0].local_state_digest()
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="锁定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=69)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


@pytest.mark.parametrize("has_ids", [False, True])
def test_chained_array_rebinds_changed_dynamic_base_and_replays(
    tmp_path: Path, has_ids: bool
) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    bulge = 0.3
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        closed=True,
        bulges=(bulge, 0, 0, 0) if bulge else (),
    )
    entities = [first]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    if has_ids:
        entities = [
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 4))
            for item in entities
        ]
        first = entities[0]
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0, rotation_deg=angle),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "vertex", 1)
            )
            if source == refs[1]
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "segment", 1), 0.25, 4
    )
    target = resolve_attachment_local(attachment, {entities[-1].entity_id: entities[-1]})
    assert target is not None
    datum = DatumIdentifier(uuid4().hex, "A", (20, 50), target, attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (25, 50),
        leader_target_mm=target,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reverse = replace(
        first,
        points_mm=(first.points_mm[0], *reversed(first.points_mm[1:])),
        point_ids=(first.point_ids[0], *reversed(first.point_ids[1:])) if has_ids else (),
        bulges=(0, 0, 0, -bulge) if bulge else (),
    )
    revised = replace(sketch, entities=(reverse, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(first.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="基点|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=69)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 70
    original_arrays = services.kernel.associative_arrays
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=70)
    changed = next(
        array for array in services.kernel.associative_arrays if array.base_point is not None
    )
    assert changed.base_point is not None and changed.base_point.reference is not None
    assert changed.base_point.reference.index == 3
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert updated.target_mm == pytest.approx(target)
    assert updated_frame.leader_target_mm == pytest.approx(target)
    loaded.bus.undo_operation()
    assert services.kernel.associative_arrays == original_arrays
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert changed in services.kernel.associative_arrays
    path = tmp_path / "rebound-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.associative_arrays == services.kernel.associative_arrays
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)


def test_chained_rebound_base_rejects_locked_attachment_atomically() -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    has_ids, bulge = True, 0.3
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    first = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        closed=True,
        bulges=(bulge, 0, 0, 0) if bulge else (),
    )
    entities = [first]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    if has_ids:
        entities = [
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 4))
            for item in entities
        ]
        first = entities[0]
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0, rotation_deg=angle),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "vertex", 1)
            )
            if source == refs[1]
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "segment", 1), 0.25, 4
    )
    target = resolve_attachment_local(attachment, {entities[-1].entity_id: entities[-1]})
    assert target is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("REBINDBASE"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 50), target, attachment=attachment, layer_name="REBINDBASE"
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (25, 50),
        leader_target_mm=target,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reverse = replace(
        first,
        points_mm=(first.points_mm[0], *reversed(first.points_mm[1:])),
        point_ids=(first.point_ids[0], *reversed(first.point_ids[1:])) if has_ids else (),
        bulges=(0, 0, 0, -bulge) if bulge else (),
    )
    revised = replace(sketch, entities=(reverse, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(first.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "REBINDBASE" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    before = services.kernel.sketches
    before_arrays = services.kernel.associative_arrays
    params["revisions"][0]["base_state_sha256"] = before[0].local_state_digest()
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="锁定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=70)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before
    assert services.kernel.associative_arrays == before_arrays
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


@pytest.mark.parametrize("has_ids", [False, True])
def test_three_level_chain_rebinds_multiple_dynamic_bases(tmp_path: Path, has_ids: bool) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(uuid4().hex, ((0, y), (10, y), (10, y + 10))) for y in (0, 20, 40, 60)
    )
    if has_ids:
        entities = tuple(
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 3))
            for item in entities
        )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target in zip(refs[:-1], refs[1:], strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "vertex", 0)
            )
            if source in refs[1:]
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 45),
        (2.5, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[2].entity_id, "segment", 0), 0.25, 2
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 66),
        leader_target_mm=(2.5, 60),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 2
        ),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reversed_source = replace(
        entities[0],
        points_mm=tuple(reversed(entities[0].points_mm)),
        point_ids=tuple(reversed(entities[0].point_ids)),
    )
    state = replace(sketch, entities=(reversed_source, *entities[1:])).to_state_mapping()
    mapping = PolylineTopologyMap(entities[0].entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    inferred, _base_rebind, version = app.exact_attached_polyline_reorder_maps(
        services, (sketch,), (replace(sketch, entities=(reversed_source, *entities[1:])),)
    )
    assert inferred == tuple(params["polyline_topology_maps"])
    assert version == 70
    with pytest.raises(ValidationError, match="链式|关联"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=69)
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=70)
    bases = tuple(
        array.base_point
        for array in services.kernel.associative_arrays
        if array.base_point is not None
    )
    assert len(bases) == 2 and all(
        base.reference is not None and base.reference.index == 2 for base in bases
    )
    after_datum, after_frame = (
        services.kernel.drawing_datum_identifiers[0],
        services.kernel.drawing_tolerance_frames[0],
    )
    if has_ids:
        revised_entities = services.kernel.sketches[0].entities
        for before, after in zip(entities, revised_entities, strict=True):
            assert isinstance(after, PolylineEntity)
            assert after.point_ids == tuple(reversed(before.point_ids))
    assert after_datum.attachment is not None and after_datum.attachment.reference.index == 1
    assert (
        after_frame.leader_attachment is not None
        and after_frame.leader_attachment.reference.index == 1
    )
    assert after_datum.target_mm == pytest.approx(datum.target_mm)
    assert after_frame.leader_target_mm == pytest.approx(frame.leader_target_mm)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (after_datum,)
    output = tmp_path / "chain-reorder.my2d"
    save_document(loaded.document, output)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, output)
    assert reopened.kernel.drawing_datum_identifiers == (after_datum,)
    assert reopened.kernel.drawing_tolerance_frames == (after_frame,)


@pytest.mark.parametrize("kind", ["start", "end"])
def test_three_level_chain_rebinds_endpoint_dynamic_bases(
    tmp_path: Path, kind: Literal["start", "end"]
) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    has_ids = True
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(uuid4().hex, ((0, y), (10, y), (10, y + 10))) for y in (0, 20, 40, 60)
    )
    if has_ids:
        entities = tuple(
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 3))
            for item in entities
        )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target in zip(refs[:-1], refs[1:], strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, kind)
            )
            if source in refs[1:]
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 45),
        (2.5, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[2].entity_id, "segment", 0), 0.25, 2
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 66),
        leader_target_mm=(2.5, 60),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 2
        ),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reversed_source = replace(
        entities[0],
        points_mm=tuple(reversed(entities[0].points_mm)),
        point_ids=tuple(reversed(entities[0].point_ids)),
    )
    state = replace(sketch, entities=(reversed_source, *entities[1:])).to_state_mapping()
    mapping = PolylineTopologyMap(entities[0].entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    inferred, _base_rebind, version = app.exact_attached_polyline_reorder_maps(
        services, (sketch,), (replace(sketch, entities=(reversed_source, *entities[1:])),)
    )
    assert inferred == tuple(params["polyline_topology_maps"])
    assert version == 70
    with pytest.raises(ValidationError, match="链式|关联"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=69)
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=70)
    bases = tuple(
        array.base_point
        for array in services.kernel.associative_arrays
        if array.base_point is not None
    )
    assert len(bases) == 2 and all(
        base.reference is not None
        and base.reference.kind == "vertex"
        and base.reference.index == (2 if kind == "start" else 0)
        for base in bases
    )
    after_datum, after_frame = (
        services.kernel.drawing_datum_identifiers[0],
        services.kernel.drawing_tolerance_frames[0],
    )
    if has_ids:
        revised_entities = services.kernel.sketches[0].entities
        for before, after in zip(entities, revised_entities, strict=True):
            assert isinstance(after, PolylineEntity)
            assert after.point_ids == tuple(reversed(before.point_ids))
    assert after_datum.attachment is not None and after_datum.attachment.reference.index == 1
    assert (
        after_frame.leader_attachment is not None
        and after_frame.leader_attachment.reference.index == 1
    )
    assert after_datum.target_mm == pytest.approx(datum.target_mm)
    assert after_frame.leader_target_mm == pytest.approx(frame.leader_target_mm)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (after_datum,)
    output = tmp_path / "chain-reorder.my2d"
    save_document(loaded.document, output)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, output)
    assert reopened.kernel.drawing_datum_identifiers == (after_datum,)
    assert reopened.kernel.drawing_tolerance_frames == (after_frame,)


def test_chain_rebinding_rejects_member_tangency_atomically() -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    has_ids = True
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(uuid4().hex, ((0, y), (10, y), (10, y + 10))) for y in (0, 20, 40, 60)
    )
    if has_ids:
        entities = tuple(
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 3))
            for item in entities
        )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target in zip(refs[:-1], refs[1:], strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "vertex", 0)
            )
            if source in refs[1:]
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    circle = CircleEntity(uuid4().hex, (5, 42), 2)
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, other, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketch.sketch_id, entities[2].entity_id, 0),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add",
        {"relation": relation.to_mapping(), "revisions": []},
        "local",
        version=12,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 45),
        (2.5, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[2].entity_id, "segment", 0), 0.25, 2
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 66),
        leader_target_mm=(2.5, 60),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 2
        ),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reversed_source = replace(
        entities[0],
        points_mm=tuple(reversed(entities[0].points_mm)),
        point_ids=tuple(reversed(entities[0].point_ids)),
    )
    state = replace(sketch, entities=(reversed_source, *entities[1:])).to_state_mapping()
    mapping = PolylineTopologyMap(entities[0].entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    before = services.kernel.sketches
    before_arrays = services.kernel.associative_arrays
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="相切"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=70)
    with pytest.raises(ValidationError, match="相切"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=77)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before
    assert services.kernel.associative_arrays == before_arrays
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_cross_sketch_chain_rebinds_dynamic_base_and_saves(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((0, y), (10, y), (10, y + 10)),
            point_ids=new_curve_point_identities(identity, "polyline", 3),
        )
        for identity, y in ((uuid4().hex, 0), (uuid4().hex, 20), (uuid4().hex, 40))
    )
    sketches = tuple(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,)) for item in entities)
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(
        ArrayEntityRef(sketch.sketch_id, entity.entity_id)
        for sketch, entity in zip(sketches, entities, strict=True)
    )
    for position, (source, target) in enumerate(zip(refs[:-1], refs[1:], strict=True)):
        array = AssociativeRectArray(
            uuid4().hex,
            sketches[0].frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "start")
            )
            if position == 1
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketches[2].sketch_id, SketchGeometryReference(entities[2].entity_id, "segment", 0), 0.25, 2
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 45), (2.5, 40), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    reversed_source = replace(
        entities[0],
        points_mm=tuple(reversed(entities[0].points_mm)),
        point_ids=tuple(reversed(entities[0].point_ids)),
    )
    revised = replace(sketches[0], entities=(reversed_source,))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(entities[0].entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": sketches[0].sketch_id,
                "base_state_sha256": sketches[0].local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketches[0].sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    records, _, version = app.exact_attached_polyline_reorder_maps(
        services, sketches, (revised, *sketches[1:])
    )
    assert records == tuple(params["polyline_topology_maps"]) and version == 70
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=70)
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.target_mm == pytest.approx(datum.target_mm)
    assert updated.attachment is not None and updated.attachment.reference.index == 1
    base = next(
        array.base_point
        for array in services.kernel.associative_arrays
        if array.base_point is not None
    )
    assert base is not None and base.reference is not None and base.reference.index == 2
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    path = tmp_path / "cross-sketch-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.associative_arrays == services.kernel.associative_arrays


def test_chain_rebinds_source_and_downstream_bases_together(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    has_ids = True
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(uuid4().hex, ((0, y), (10, y), (10, y + 10))) for y in (0, 20, 40, 60)
    )
    if has_ids:
        entities = tuple(
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 3))
            for item in entities
        )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target in zip(refs[:-1], refs[1:], strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "vertex", 0)
            )
            if source in refs
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 45),
        (2.5, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[2].entity_id, "segment", 0), 0.25, 2
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 66),
        leader_target_mm=(2.5, 60),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 2
        ),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reversed_source = replace(
        entities[0],
        points_mm=tuple(reversed(entities[0].points_mm)),
        point_ids=tuple(reversed(entities[0].point_ids)),
    )
    state = replace(sketch, entities=(reversed_source, *entities[1:])).to_state_mapping()
    mapping = PolylineTopologyMap(entities[0].entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    inferred, _base_rebind, version = app.exact_attached_polyline_reorder_maps(
        services, (sketch,), (replace(sketch, entities=(reversed_source, *entities[1:])),)
    )
    assert inferred == tuple(params["polyline_topology_maps"])
    assert version == 70
    with pytest.raises(ValidationError, match="链式|关联"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=69)
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=70)
    bases = tuple(
        array.base_point
        for array in services.kernel.associative_arrays
        if array.base_point is not None
    )
    assert len(bases) == 3 and all(
        base.reference is not None and base.reference.index == 2 for base in bases
    )
    after_datum, after_frame = (
        services.kernel.drawing_datum_identifiers[0],
        services.kernel.drawing_tolerance_frames[0],
    )
    if has_ids:
        revised_entities = services.kernel.sketches[0].entities
        for before, after in zip(entities, revised_entities, strict=True):
            assert isinstance(after, PolylineEntity)
            assert after.point_ids == tuple(reversed(before.point_ids))
    assert after_datum.attachment is not None and after_datum.attachment.reference.index == 1
    assert (
        after_frame.leader_attachment is not None
        and after_frame.leader_attachment.reference.index == 1
    )
    assert after_datum.target_mm == pytest.approx(datum.target_mm)
    assert after_frame.leader_target_mm == pytest.approx(frame.leader_target_mm)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (after_datum,)
    output = tmp_path / "chain-reorder.my2d"
    save_document(loaded.document, output)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, output)
    assert reopened.kernel.drawing_datum_identifiers == (after_datum,)
    assert reopened.kernel.drawing_tolerance_frames == (after_frame,)


@pytest.mark.parametrize("with_tangency", [False, True])
def test_chain_keeps_unchanged_replacement_and_deep_annotation_on_reorder(
    tmp_path: Path, with_tangency: bool
) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    b = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[2],), (ArrayMember(refs[2], refs[3], 1, 0),)
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[3].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    source = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(entities[0].point_ids[0], *reversed(entities[0].point_ids[1:])),
    )
    revised = replace(sketch, entities=(source, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="替换|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=70)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 71
    arrays = services.kernel.associative_arrays
    original_sketches = services.kernel.sketches
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=71)
    assert services.kernel.sketches[0].entities[1:] == entities[1:]
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.associative_arrays == arrays
    loaded.bus.undo_operation()
    assert services.kernel.sketches == original_sketches
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    path = tmp_path / "unchanged-replacement-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)
    assert reopened.kernel.associative_arrays == arrays
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)
        assert reopened.kernel.cross_sketch_tangencies == (relation,)


def test_chain_replacement_rejects_changed_anchor_atomically() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_tangency = False
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    b = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[2],), (ArrayMember(refs[2], refs[3], 1, 0),)
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[3].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    source = replace(
        entities[0],
        points_mm=(entities[0].points_mm[-1], *entities[0].points_mm[:-1]),
        point_ids=(entities[0].point_ids[-1], *entities[0].point_ids[:-1]),
    )
    revised = replace(sketch, entities=(source, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (1, 2, 3, 0), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    count = loaded.document.command_count
    before = services.kernel.sketches
    arrays = services.kernel.associative_arrays
    records, _, _ = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert not records
    with pytest.raises(ValidationError, match="替换|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=71)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before
    assert services.kernel.associative_arrays == arrays
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("with_base", [False, True])
def test_chain_reordered_replacement_rebinds_deep_annotation(
    tmp_path: Path, with_base: bool
) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_tangency = False
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[2], reference=SketchGeometryReference(refs[2].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[3].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(entities[1].point_ids[0], *reversed(entities[1].point_ids[1:])),
    )
    revised = replace(sketch, entities=(entities[0], source, *entities[2:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="替换|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=71)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 72
    arrays = services.kernel.associative_arrays
    original_sketches = services.kernel.sketches
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=72)
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert (
        updated_frame.leader_attachment is not None
        and updated_frame.leader_attachment.reference.index == 3
    )
    assert updated_frame.leader_target_mm == pytest.approx(datum.target_mm)
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    assert services.kernel.drawing_datum_identifiers == (updated,)
    if with_base:
        changed_base = next(
            array.base_point
            for array in services.kernel.associative_arrays
            if array.base_point is not None
        )
        assert (
            changed_base is not None
            and changed_base.reference is not None
            and changed_base.reference.index == 3
        )
    else:
        assert services.kernel.associative_arrays == arrays
    final_arrays = services.kernel.associative_arrays
    loaded.bus.undo_operation()
    assert services.kernel.sketches == original_sketches
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated,)
    path = tmp_path / "unchanged-replacement-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)
    assert reopened.kernel.associative_arrays == final_arrays
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)
        assert reopened.kernel.cross_sketch_tangencies == (relation,)


def test_generated_replacement_source_reorders_through_chain(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (20, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    one = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 10, (refs[0],), (ArrayMember(refs[0], refs[1], 0, 1),)
    )
    two = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    three = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[3],), (ArrayMember(refs[3], refs[4], 1, 0),)
    )
    for array in (three, two, one):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    source = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(entities[0].point_ids[0], *reversed(entities[0].point_ids[1:])),
    )
    revised = replace(sketch, entities=(source, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="替换|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=71)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 72
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=72)
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    for idx in (1, 3, 4):
        result = services.kernel.sketches[0].entities[idx]
        assert isinstance(result, PolylineEntity)
        assert result.point_ids == (
            entities[idx].point_ids[0],
            *reversed(entities[idx].point_ids[1:]),
        )
    loaded.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)
    loaded.bus.redo_operation()
    path = tmp_path / "generated-replacement.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.associative_arrays == services.kernel.associative_arrays


def test_chain_reordered_replacement_rejects_changed_anchor() -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_base = False
    with_tangency = False
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[2], reference=SketchGeometryReference(refs[2].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[3].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[-1], *entities[1].points_mm[:-1]),
        point_ids=(entities[1].point_ids[-1], *entities[1].point_ids[:-1]),
    )
    revised = replace(sketch, entities=(entities[0], source, *entities[2:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (1, 2, 3, 0), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    count = loaded.document.command_count
    before, arrays = services.kernel.sketches, services.kernel.associative_arrays
    records, _, _ = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert not records
    with pytest.raises(ValidationError, match="替换|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=72)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before and services.kernel.associative_arrays == arrays
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_chain_reordered_replacement_rejects_changed_member_tangency() -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_base = False
    with_tangency = True
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[2], reference=SketchGeometryReference(refs[2].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[3].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(entities[1].point_ids[0], *reversed(entities[1].point_ids[1:])),
    )
    revised = replace(sketch, entities=(entities[0], source, *entities[2:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    assert relation is not None
    count = loaded.document.command_count
    before, arrays = services.kernel.sketches, services.kernel.associative_arrays
    with pytest.raises(ValidationError, match="相切"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=72)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before and services.kernel.associative_arrays == arrays
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_chain_reordered_replacement_rejects_locked_annotation() -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_base = True
    with_tangency = False
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[2], reference=SketchGeometryReference(refs[2].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[3].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    layers = services.kernel.drawing_layers.add(SketchLayer("REPLACEMENT_LOCK"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment, layer_name="REPLACEMENT_LOCK"
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(entities[1].point_ids[0], *reversed(entities[1].point_ids[1:])),
    )
    revised = replace(sketch, entities=(entities[0], source, *entities[2:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "REPLACEMENT_LOCK" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    before, arrays = services.kernel.sketches, services.kernel.associative_arrays
    params["revisions"][0]["base_state_sha256"] = before[0].local_state_digest()
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="锁定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=72)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before and services.kernel.associative_arrays == arrays
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)


@pytest.mark.parametrize("source_kind", ["anchor", "geometry"])
def test_chain_extra_output_follows_its_actual_geometry_source(
    tmp_path: Path, source_kind: str
) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 1, 0),),
        extra_outputs=(ArrayExtraOutput(refs[2], refs[3], refs[0], 1, 0),),
    )
    b = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[3],), (ArrayMember(refs[3], refs[4], 1, 0),)
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    idx = 0 if source_kind == "anchor" else 2
    old = entities[idx]
    changed = replace(
        old,
        points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
        point_ids=(old.point_ids[0], *reversed(old.point_ids[1:])),
    )
    revised = replace(
        sketch,
        entities=tuple(changed if item.entity_id == old.entity_id else item for item in entities),
    )
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(old.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="额外|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=72)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 73
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=73)
    updated, updated_frame = (
        services.kernel.drawing_datum_identifiers[0],
        services.kernel.drawing_tolerance_frames[0],
    )
    assert updated.target_mm == pytest.approx(datum.target_mm)
    assert updated_frame.leader_target_mm == pytest.approx(datum.target_mm)
    assert updated.attachment is not None and updated_frame.leader_attachment is not None
    assert updated.attachment.reference.index == (0 if source_kind == "anchor" else 3)
    assert updated_frame.leader_attachment.reference.index == (0 if source_kind == "anchor" else 3)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    path = tmp_path / f"extra-chain-{source_kind}.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)


def test_chain_extra_output_uses_shared_anchor_geometry(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    source_kind = "geometry"
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 1, 0),),
        extra_outputs=(ArrayExtraOutput(refs[0], refs[3], refs[0], 1, 0),),
    )
    b = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[3],), (ArrayMember(refs[3], refs[4], 1, 0),)
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    idx = 0
    old = entities[idx]
    changed = replace(
        old,
        points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
        point_ids=(old.point_ids[0], *reversed(old.point_ids[1:])),
    )
    revised = replace(
        sketch,
        entities=tuple(changed if item.entity_id == old.entity_id else item for item in entities),
    )
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(old.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="额外|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=72)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 73
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=73)
    updated, updated_frame = (
        services.kernel.drawing_datum_identifiers[0],
        services.kernel.drawing_tolerance_frames[0],
    )
    assert updated.target_mm == pytest.approx(datum.target_mm)
    assert updated_frame.leader_target_mm == pytest.approx(datum.target_mm)
    assert updated.attachment is not None and updated_frame.leader_attachment is not None
    assert updated.attachment.reference.index == (0 if source_kind == "anchor" else 3)
    assert updated_frame.leader_attachment.reference.index == (0 if source_kind == "anchor" else 3)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    path = tmp_path / f"extra-chain-{source_kind}.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)


@pytest.mark.parametrize("with_base", [False, True])
def test_generated_extra_source_reorders_through_chain(tmp_path: Path, with_base: bool) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (20, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
            (uuid4().hex, (0, 20)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    one = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 10, (refs[0],), (ArrayMember(refs[0], refs[1], 0, 1),)
    )
    two = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[5], 1, 0),),
        extra_outputs=(ArrayExtraOutput(refs[1], refs[3], refs[2], 1, 0),),
    )
    three = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[3],),
        (ArrayMember(refs[3], refs[4], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[3], reference=SketchGeometryReference(refs[3].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (three, two, one):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    source = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(entities[0].point_ids[0], *reversed(entities[0].point_ids[1:])),
    )
    revised = replace(sketch, entities=(source, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="替换|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=72)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 73
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=73)
    updated = services.kernel.drawing_datum_identifiers[0]
    if with_base:
        changed_base = next(
            array.base_point
            for array in services.kernel.associative_arrays
            if array.base_point is not None
        )
        assert (
            changed_base is not None
            and changed_base.reference is not None
            and changed_base.reference.index == 3
        )
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    for idx in (1, 3, 4):
        result = services.kernel.sketches[0].entities[idx]
        assert isinstance(result, PolylineEntity)
        assert result.point_ids == (
            entities[idx].point_ids[0],
            *reversed(entities[idx].point_ids[1:]),
        )
    loaded.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)
    loaded.bus.redo_operation()
    path = tmp_path / "generated-replacement.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.associative_arrays == services.kernel.associative_arrays


@pytest.mark.parametrize("case", ["anchor", "locked", "tangency"])
def test_chain_extra_output_rejects_unproven_changes_atomically(case: str) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 1, 0),),
        extra_outputs=(ArrayExtraOutput(refs[2], refs[3], refs[0], 1, 0),),
    )
    b = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[3],), (ArrayMember(refs[3], refs[4], 1, 0),)
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if case == "tangency":
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[4].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    layers = services.kernel.drawing_layers
    if case == "locked":
        layers = layers.add(SketchLayer("EXTRA_LOCK"))
        loaded.bus.execute(
            "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 46),
        (2.5, 40),
        attachment=attachment,
        layer_name="EXTRA_LOCK" if case == "locked" else "0",
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    idx = 0 if case == "anchor" else 2
    old = entities[idx]
    changed = replace(
        old,
        points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
        point_ids=(old.point_ids[0], *reversed(old.point_ids[1:])),
    )
    if case == "anchor":
        changed = replace(
            old,
            points_mm=(old.points_mm[-1], *old.points_mm[:-1]),
            point_ids=(old.point_ids[-1], *old.point_ids[:-1]),
        )
    revised = replace(
        sketch,
        entities=tuple(changed if item.entity_id == old.entity_id else item for item in entities),
    )
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(
        old.entity_id, (1, 2, 3, 0) if case == "anchor" else (0, 3, 2, 1), 4, True
    )
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    if case == "locked":
        locked = replace(
            layers,
            layers=tuple(
                replace(layer, locked=True) if layer.name == "EXTRA_LOCK" else layer
                for layer in layers.layers
            ),
        )
        loaded.bus.execute(
            "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    before, arrays = services.kernel.sketches, services.kernel.associative_arrays
    params["revisions"][0]["base_state_sha256"] = next(
        item for item in before if item.sketch_id == sketch.sketch_id
    ).local_state_digest()
    count = loaded.document.command_count
    match = {"anchor": "额外|关联|重绑定", "locked": "锁定", "tangency": "相切"}[case]
    with pytest.raises(ValidationError, match=match):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=73)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before and services.kernel.associative_arrays == arrays
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)


def test_chain_simultaneous_anchor_and_replacement_reorders_replay(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_base = False
    with_tangency = False
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[2], reference=SketchGeometryReference(refs[2].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[3].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(entities[1].point_ids[0], *reversed(entities[1].point_ids[1:])),
    )
    anchor = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(entities[0].point_ids[0], *reversed(entities[0].point_ids[1:])),
    )
    revised = replace(sketch, entities=(anchor, source, *entities[2:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {
                "sketch_id": sketch.sketch_id,
                "mapping": PolylineTopologyMap(
                    anchor.entity_id, (0, 3, 2, 1), 4, True
                ).to_mapping(),
            },
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()},
        ],
    }
    with pytest.raises(ValidationError, match="替换|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=73)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 74
    arrays = services.kernel.associative_arrays
    original_sketches = services.kernel.sketches
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=74)
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert (
        updated_frame.leader_attachment is not None
        and updated_frame.leader_attachment.reference.index == 3
    )
    assert updated_frame.leader_target_mm == pytest.approx(datum.target_mm)
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    assert services.kernel.drawing_datum_identifiers == (updated,)
    if with_base:
        changed_base = next(
            array.base_point
            for array in services.kernel.associative_arrays
            if array.base_point is not None
        )
        assert (
            changed_base is not None
            and changed_base.reference is not None
            and changed_base.reference.index == 3
        )
    else:
        assert services.kernel.associative_arrays == arrays
    final_arrays = services.kernel.associative_arrays
    loaded.bus.undo_operation()
    assert services.kernel.sketches == original_sketches
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated,)
    path = tmp_path / "unchanged-replacement-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)
    assert reopened.kernel.associative_arrays == final_arrays
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)
        assert reopened.kernel.cross_sketch_tangencies == (relation,)


@pytest.mark.parametrize("case", ["anchor", "replacement", "locked", "tangency"])
def test_simultaneous_replacement_rejects_unproven_changes(case: str) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_base = True
    with_tangency = case == "tangency"
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[2], reference=SketchGeometryReference(refs[2].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[3].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    layers = services.kernel.drawing_layers
    if case == "locked":
        layers = layers.add(SketchLayer("SIMULTANEOUS_LOCK"))
        loaded.bus.execute(
            "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 46),
        (2.5, 40),
        attachment=attachment,
        layer_name="SIMULTANEOUS_LOCK" if case == "locked" else "0",
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(entities[1].point_ids[0], *reversed(entities[1].point_ids[1:])),
    )
    anchor = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(entities[0].point_ids[0], *reversed(entities[0].point_ids[1:])),
    )
    if case == "anchor":
        anchor = replace(
            entities[0],
            points_mm=(entities[0].points_mm[-1], *entities[0].points_mm[:-1]),
            point_ids=(entities[0].point_ids[-1], *entities[0].point_ids[:-1]),
        )
    if case == "replacement":
        source = replace(
            entities[1],
            points_mm=(entities[1].points_mm[-1], *entities[1].points_mm[:-1]),
            point_ids=(entities[1].point_ids[-1], *entities[1].point_ids[:-1]),
        )
    revised = replace(sketch, entities=(anchor, source, *entities[2:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(
        source.entity_id, (1, 2, 3, 0) if case == "replacement" else (0, 3, 2, 1), 4, True
    )
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {
                "sketch_id": sketch.sketch_id,
                "mapping": PolylineTopologyMap(
                    anchor.entity_id, (1, 2, 3, 0) if case == "anchor" else (0, 3, 2, 1), 4, True
                ).to_mapping(),
            },
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()},
        ],
    }
    if case == "locked":
        locked = replace(
            layers,
            layers=tuple(
                replace(layer, locked=True) if layer.name == "SIMULTANEOUS_LOCK" else layer
                for layer in layers.layers
            ),
        )
        loaded.bus.execute(
            "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    before, arrays = services.kernel.sketches, services.kernel.associative_arrays
    params["revisions"][0]["base_state_sha256"] = next(
        item for item in before if item.sketch_id == sketch.sketch_id
    ).local_state_digest()
    count = loaded.document.command_count
    match = {
        "anchor": "替换|关联|重绑定",
        "replacement": "替换|关联|重绑定",
        "locked": "锁定",
        "tangency": "相切",
    }[case]
    with pytest.raises(ValidationError, match=match):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=74)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before and services.kernel.associative_arrays == arrays
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)


def test_generated_replacement_and_anchor_reorder_together_replays(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (20, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    one = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 10, (refs[0],), (ArrayMember(refs[0], refs[1], 0, 1),)
    )
    two = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    three = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[3],), (ArrayMember(refs[3], refs[4], 1, 0),)
    )
    for array in (three, two, one):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    source = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(entities[0].point_ids[0], *reversed(entities[0].point_ids[1:])),
    )
    anchor = replace(
        entities[2],
        points_mm=(entities[2].points_mm[0], *reversed(entities[2].points_mm[1:])),
        point_ids=(entities[2].point_ids[0], *reversed(entities[2].point_ids[1:])),
    )
    revised = replace(sketch, entities=(source, entities[1], anchor, *entities[3:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()},
            {
                "sketch_id": sketch.sketch_id,
                "mapping": PolylineTopologyMap(
                    anchor.entity_id, (0, 3, 2, 1), 4, True
                ).to_mapping(),
            },
        ],
    }
    with pytest.raises(ValidationError, match="替换|关联|重绑定|重复|顺序"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=74)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 75
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=75)
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert (
        updated_frame.leader_attachment is not None
        and updated_frame.leader_attachment.reference.index == 3
    )
    assert updated_frame.leader_target_mm == pytest.approx(datum.target_mm)
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    for idx in (1, 3, 4):
        result = services.kernel.sketches[0].entities[idx]
        assert isinstance(result, PolylineEntity)
        assert result.point_ids == (
            entities[idx].point_ids[0],
            *reversed(entities[idx].point_ids[1:]),
        )
    loaded.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    path = tmp_path / "generated-replacement.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)
    assert reopened.kernel.associative_arrays == services.kernel.associative_arrays


@pytest.mark.parametrize("case", ["root", "anchor", "locked", "tangency"])
def test_generated_replacement_and_anchor_reject_unsafe_changes(case: str) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (20, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    one = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 10, (refs[0],), (ArrayMember(refs[0], refs[1], 0, 1),)
    )
    two = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    three = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[3],), (ArrayMember(refs[3], refs[4], 1, 0),)
    )
    for array in (three, two, one):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if case == "tangency":
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[4].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    layers = services.kernel.drawing_layers
    if case == "locked":
        layers = layers.add(SketchLayer("GEN_LOCK"))
        loaded.bus.execute(
            "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 46),
        (2.5, 40),
        attachment=attachment,
        layer_name="GEN_LOCK" if case == "locked" else "0",
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    source = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(entities[0].point_ids[0], *reversed(entities[0].point_ids[1:])),
    )
    anchor = replace(
        entities[2],
        points_mm=(entities[2].points_mm[0], *reversed(entities[2].points_mm[1:])),
        point_ids=(entities[2].point_ids[0], *reversed(entities[2].point_ids[1:])),
    )
    if case == "root":
        source = replace(
            entities[0],
            points_mm=(entities[0].points_mm[-1], *entities[0].points_mm[:-1]),
            point_ids=(entities[0].point_ids[-1], *entities[0].point_ids[:-1]),
        )
    if case == "anchor":
        anchor = replace(
            entities[2],
            points_mm=(entities[2].points_mm[-1], *entities[2].points_mm[:-1]),
            point_ids=(entities[2].point_ids[-1], *entities[2].point_ids[:-1]),
        )
    revised = replace(sketch, entities=(source, entities[1], anchor, *entities[3:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(
        source.entity_id, (1, 2, 3, 0) if case == "root" else (0, 3, 2, 1), 4, True
    )
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()},
            {
                "sketch_id": sketch.sketch_id,
                "mapping": PolylineTopologyMap(
                    anchor.entity_id, (1, 2, 3, 0) if case == "anchor" else (0, 3, 2, 1), 4, True
                ).to_mapping(),
            },
        ],
    }
    if case == "locked":
        locked = replace(
            layers,
            layers=tuple(
                replace(layer, locked=True) if layer.name == "GEN_LOCK" else layer
                for layer in layers.layers
            ),
        )
        loaded.bus.execute(
            "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    before, arrays = services.kernel.sketches, services.kernel.associative_arrays
    params["revisions"][0]["base_state_sha256"] = next(
        item for item in before if item.sketch_id == sketch.sketch_id
    ).local_state_digest()
    count = loaded.document.command_count
    match = {
        "root": "替换|关联|重绑定|锚点",
        "anchor": "替换|关联|重绑定|锚点",
        "locked": "锁定",
        "tangency": "相切",
    }[case]
    with pytest.raises(ValidationError, match=match):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=75)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before and services.kernel.associative_arrays == arrays
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)


def test_generated_extra_source_and_anchor_reorder_together_replay(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_base = True
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (20, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
            (uuid4().hex, (0, 20)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    one = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 10, (refs[0],), (ArrayMember(refs[0], refs[1], 0, 1),)
    )
    two = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[5], 1, 0),),
        extra_outputs=(ArrayExtraOutput(refs[1], refs[3], refs[2], 1, 0),),
    )
    three = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[3],),
        (ArrayMember(refs[3], refs[4], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[3], reference=SketchGeometryReference(refs[3].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (three, two, one):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    source = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(entities[0].point_ids[0], *reversed(entities[0].point_ids[1:])),
    )
    anchor = replace(
        entities[2],
        points_mm=(entities[2].points_mm[0], *reversed(entities[2].points_mm[1:])),
        point_ids=(entities[2].point_ids[0], *reversed(entities[2].point_ids[1:])),
    )
    revised = replace(sketch, entities=(source, entities[1], anchor, *entities[3:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()},
            {
                "sketch_id": sketch.sketch_id,
                "mapping": PolylineTopologyMap(
                    anchor.entity_id, (0, 3, 2, 1), 4, True
                ).to_mapping(),
            },
        ],
    }
    with pytest.raises(ValidationError, match="替换|关联|重绑定|重复|顺序"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=74)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 75
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=75)
    updated = services.kernel.drawing_datum_identifiers[0]
    if with_base:
        changed_base = next(
            array.base_point
            for array in services.kernel.associative_arrays
            if array.base_point is not None
        )
        assert (
            changed_base is not None
            and changed_base.reference is not None
            and changed_base.reference.index == 3
        )
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    for idx in (1, 3, 4):
        result = services.kernel.sketches[0].entities[idx]
        assert isinstance(result, PolylineEntity)
        assert result.point_ids == (
            entities[idx].point_ids[0],
            *reversed(entities[idx].point_ids[1:]),
        )
    loaded.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)
    loaded.bus.redo_operation()
    path = tmp_path / "generated-replacement.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.associative_arrays == services.kernel.associative_arrays


@pytest.mark.parametrize("case", ["root", "anchor", "locked", "tangency"])
def test_generated_extra_source_and_anchor_reject_unsafe_changes(case: str) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (20, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
            (uuid4().hex, (0, 20)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    one = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 10, (refs[0],), (ArrayMember(refs[0], refs[1], 0, 1),)
    )
    two = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[5], 1, 0),),
        extra_outputs=(ArrayExtraOutput(refs[1], refs[3], refs[2], 1, 0),),
    )
    three = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[3],), (ArrayMember(refs[3], refs[4], 1, 0),)
    )
    for array in (three, two, one):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if case == "tangency":
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[4].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    layers = services.kernel.drawing_layers
    if case == "locked":
        layers = layers.add(SketchLayer("GEN_LOCK"))
        loaded.bus.execute(
            "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 46),
        (2.5, 40),
        attachment=attachment,
        layer_name="GEN_LOCK" if case == "locked" else "0",
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    source = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(entities[0].point_ids[0], *reversed(entities[0].point_ids[1:])),
    )
    anchor = replace(
        entities[2],
        points_mm=(entities[2].points_mm[0], *reversed(entities[2].points_mm[1:])),
        point_ids=(entities[2].point_ids[0], *reversed(entities[2].point_ids[1:])),
    )
    if case == "root":
        source = replace(
            entities[0],
            points_mm=(entities[0].points_mm[-1], *entities[0].points_mm[:-1]),
            point_ids=(entities[0].point_ids[-1], *entities[0].point_ids[:-1]),
        )
    if case == "anchor":
        anchor = replace(
            entities[2],
            points_mm=(entities[2].points_mm[-1], *entities[2].points_mm[:-1]),
            point_ids=(entities[2].point_ids[-1], *entities[2].point_ids[:-1]),
        )
    revised = replace(sketch, entities=(source, entities[1], anchor, *entities[3:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(
        source.entity_id, (1, 2, 3, 0) if case == "root" else (0, 3, 2, 1), 4, True
    )
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()},
            {
                "sketch_id": sketch.sketch_id,
                "mapping": PolylineTopologyMap(
                    anchor.entity_id, (1, 2, 3, 0) if case == "anchor" else (0, 3, 2, 1), 4, True
                ).to_mapping(),
            },
        ],
    }
    if case == "locked":
        locked = replace(
            layers,
            layers=tuple(
                replace(layer, locked=True) if layer.name == "GEN_LOCK" else layer
                for layer in layers.layers
            ),
        )
        loaded.bus.execute(
            "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    before, arrays = services.kernel.sketches, services.kernel.associative_arrays
    params["revisions"][0]["base_state_sha256"] = next(
        item for item in before if item.sketch_id == sketch.sketch_id
    ).local_state_digest()
    count = loaded.document.command_count
    match = {
        "root": "替换|关联|重绑定|锚点|拓扑|映射",
        "anchor": "替换|关联|重绑定|锚点",
        "locked": "锁定",
        "tangency": "相切",
    }[case]
    with pytest.raises(ValidationError, match=match):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=75)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before and services.kernel.associative_arrays == arrays
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)


def test_extra_source_generated_inside_same_array_reorders_safely(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (20, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (30, 20)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    first = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        10,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1),),
        extra_outputs=(ArrayExtraOutput(refs[1], refs[2], refs[0], 0, 1),),
    )
    second = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[2],), (ArrayMember(refs[2], refs[3], 1, 0),)
    )
    for array in (second, first):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (35, 26), (32.5, 20), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    old = entities[0]
    changed = replace(
        old,
        points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
        point_ids=(old.point_ids[0], *reversed(old.point_ids[1:])),
    )
    revised = replace(sketch, entities=(changed, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(old.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="关联|重绑定|成员|重复"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=74)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 75
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=75)
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    path = tmp_path / "internal-extra.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)


def test_internal_replacement_source_reorders_through_chain(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (20, 0)),
            (uuid4().hex, (20, 20)),
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    one = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0], refs[2]),
        (
            ArrayMember(refs[0], refs[1], 1, 0),
            ArrayMember(refs[2], refs[3], 1, 0, replacement=ArrayReplacement(refs[1])),
        ),
    )
    three = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[3],), (ArrayMember(refs[3], refs[4], 1, 0),)
    )
    for array in (three, one):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    source = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(entities[0].point_ids[0], *reversed(entities[0].point_ids[1:])),
    )
    revised = replace(sketch, entities=(source, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="替换|关联|重绑定|成员"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=74)
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain

    assert simple_array_reorder_chain(
        services.kernel.associative_arrays,
        frozenset(((sketch.sketch_id, source.entity_id),)),
        stable_anchor_sources=frozenset(((sketch.sketch_id, source.entity_id),)),
        allow_stable_bases=True,
        allow_base_rebinding=True,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
        allow_simultaneous_replacements=True,
        defer_affected_dependencies=True,
    ) == ((refs[0], refs[1]), (refs[1], refs[3]), (refs[3], refs[4]))
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 75
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=75)
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    for idx in (1, 3, 4):
        result = services.kernel.sketches[0].entities[idx]
        assert isinstance(result, PolylineEntity)
        assert result.point_ids == (
            entities[idx].point_ids[0],
            *reversed(entities[idx].point_ids[1:]),
        )
    loaded.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)
    loaded.bus.redo_operation()
    path = tmp_path / "generated-replacement.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.associative_arrays == services.kernel.associative_arrays


def test_nested_extra_outputs_inside_same_array_reorder_safely(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (20, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (30, 20)),
            (uuid4().hex, (30, 0)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    first = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        10,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1),),
        extra_outputs=(
            ArrayExtraOutput(refs[1], refs[2], refs[0], 0, 1),
            ArrayExtraOutput(refs[2], refs[4], refs[0], 0, 1),
        ),
    )
    second = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[4],), (ArrayMember(refs[4], refs[3], 1, 0),)
    )
    for array in (second, first):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (35, 26), (32.5, 20), attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    old = entities[0]
    changed = replace(
        old,
        points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
        point_ids=(old.point_ids[0], *reversed(old.point_ids[1:])),
    )
    revised = replace(sketch, entities=(changed, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(old.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="关联|重绑定|成员|重复"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=74)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 75
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=75)
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    path = tmp_path / "internal-extra.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)


def test_chain_reordered_replacement_with_unrelated_extra_replays(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_base = True
    with_tangency = False
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
            (uuid4().hex, (60, 0)),
            (uuid4().hex, (0, 20)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
        extra_outputs=(ArrayExtraOutput(refs[4], refs[5], refs[0], 1, 0),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[2], reference=SketchGeometryReference(refs[2].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[3].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(entities[1].point_ids[0], *reversed(entities[1].point_ids[1:])),
    )
    revised = replace(sketch, entities=(entities[0], source, *entities[2:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="替换|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=75)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 76
    arrays = services.kernel.associative_arrays
    original_sketches = services.kernel.sketches
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=76)
    assert services.kernel.sketches[0].entities[4:] == entities[4:]
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert (
        updated_frame.leader_attachment is not None
        and updated_frame.leader_attachment.reference.index == 3
    )
    assert updated_frame.leader_target_mm == pytest.approx(datum.target_mm)
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    assert services.kernel.drawing_datum_identifiers == (updated,)
    if with_base:
        changed_base = next(
            array.base_point
            for array in services.kernel.associative_arrays
            if array.base_point is not None
        )
        assert (
            changed_base is not None
            and changed_base.reference is not None
            and changed_base.reference.index == 3
        )
    else:
        assert services.kernel.associative_arrays == arrays
    final_arrays = services.kernel.associative_arrays
    loaded.bus.undo_operation()
    assert services.kernel.sketches == original_sketches
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated,)
    path = tmp_path / "unchanged-replacement-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)
    assert reopened.kernel.associative_arrays == final_arrays
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)
        assert reopened.kernel.cross_sketch_tangencies == (relation,)


@pytest.mark.parametrize("case", ["anchor", "locked", "tangency"])
def test_mixed_replacement_extra_rejects_unproven_changes(case: str) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_base = True
    with_tangency = case == "tangency"
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
            (uuid4().hex, (60, 0)),
            (uuid4().hex, (0, 20)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
        extra_outputs=(ArrayExtraOutput(refs[4], refs[5], refs[0], 1, 0),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[2], reference=SketchGeometryReference(refs[2].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[3].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    layers = services.kernel.drawing_layers
    if case == "locked":
        layers = layers.add(SketchLayer("MIXED_LOCK"))
        loaded.bus.execute(
            "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 46),
        (2.5, 40),
        attachment=attachment,
        layer_name="MIXED_LOCK" if case == "locked" else "0",
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(entities[1].point_ids[0], *reversed(entities[1].point_ids[1:])),
    )
    if case == "anchor":
        source = replace(
            entities[1],
            points_mm=(entities[1].points_mm[-1], *entities[1].points_mm[:-1]),
            point_ids=(entities[1].point_ids[-1], *entities[1].point_ids[:-1]),
        )
    revised = replace(sketch, entities=(entities[0], source, *entities[2:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(
        source.entity_id, (1, 2, 3, 0) if case == "anchor" else (0, 3, 2, 1), 4, True
    )
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    if case == "locked":
        locked = replace(
            layers,
            layers=tuple(
                replace(layer, locked=True) if layer.name == "MIXED_LOCK" else layer
                for layer in layers.layers
            ),
        )
        loaded.bus.execute(
            "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
    before, arrays = services.kernel.sketches, services.kernel.associative_arrays
    params["revisions"][0]["base_state_sha256"] = next(
        item for item in before if item.sketch_id == sketch.sketch_id
    ).local_state_digest()
    count = loaded.document.command_count
    match = {"anchor": "替换|关联|重绑定|锚点", "locked": "锁定", "tangency": "相切"}[case]
    with pytest.raises(ValidationError, match=match):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=76)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before and services.kernel.associative_arrays == arrays
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)


def test_chain_replacement_and_extra_share_reordered_geometry_source(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_base = True
    with_tangency = False
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
            (uuid4().hex, (60, 0)),
            (uuid4().hex, (0, 20)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
        extra_outputs=(ArrayExtraOutput(refs[1], refs[5], refs[0], 1, 0),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[2], reference=SketchGeometryReference(refs[2].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[3].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    extra_attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[5].entity_id, "segment", 0), 0.25, 4
    )
    extra_datum = DatumIdentifier(uuid4().hex, "B", (5, 26), (2.5, 20), attachment=extra_attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {
            "add_datums": [datum.to_mapping(), extra_datum.to_mapping()],
            "add_frames": [frame.to_mapping()],
        },
        "local",
    )
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(entities[1].point_ids[0], *reversed(entities[1].point_ids[1:])),
    )
    revised = replace(sketch, entities=(entities[0], source, *entities[2:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="替换|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=75)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 76
    arrays = services.kernel.associative_arrays
    original_sketches = services.kernel.sketches
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=76)
    assert services.kernel.sketches[0].entities[4] == entities[4]
    extra = services.kernel.sketches[0].entities[5]
    assert isinstance(extra, PolylineEntity)
    assert extra.point_ids == (entities[5].point_ids[0], *reversed(entities[5].point_ids[1:]))
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    updated_extra = services.kernel.drawing_datum_identifiers[1]
    assert updated_extra.attachment is not None and updated_extra.attachment.reference.index == 3
    assert updated_extra.target_mm == pytest.approx(extra_datum.target_mm)
    assert (
        updated_frame.leader_attachment is not None
        and updated_frame.leader_attachment.reference.index == 3
    )
    assert updated_frame.leader_target_mm == pytest.approx(datum.target_mm)
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    assert services.kernel.drawing_datum_identifiers == (updated, updated_extra)
    if with_base:
        changed_base = next(
            array.base_point
            for array in services.kernel.associative_arrays
            if array.base_point is not None
        )
        assert (
            changed_base is not None
            and changed_base.reference is not None
            and changed_base.reference.index == 3
        )
    else:
        assert services.kernel.associative_arrays == arrays
    final_arrays = services.kernel.associative_arrays
    loaded.bus.undo_operation()
    assert services.kernel.sketches == original_sketches
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated, updated_extra)
    path = tmp_path / "unchanged-replacement-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated, updated_extra)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)
    assert reopened.kernel.associative_arrays == final_arrays
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)
        assert reopened.kernel.cross_sketch_tangencies == (relation,)


def test_mixed_replacement_extra_share_simultaneously_reordered_sources(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_base = True
    with_tangency = False
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
            (uuid4().hex, (60, 0)),
            (uuid4().hex, (0, 20)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
        extra_outputs=(ArrayExtraOutput(refs[1], refs[5], refs[0], 1, 0),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[2], reference=SketchGeometryReference(refs[2].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 42), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[3].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    extra_attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[5].entity_id, "segment", 0), 0.25, 4
    )
    extra_datum = DatumIdentifier(uuid4().hex, "B", (5, 26), (2.5, 20), attachment=extra_attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {
            "add_datums": [datum.to_mapping(), extra_datum.to_mapping()],
            "add_frames": [frame.to_mapping()],
        },
        "local",
    )
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(entities[1].point_ids[0], *reversed(entities[1].point_ids[1:])),
    )
    anchor = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(entities[0].point_ids[0], *reversed(entities[0].point_ids[1:])),
    )
    revised = replace(sketch, entities=(anchor, source, *entities[2:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {
                "sketch_id": sketch.sketch_id,
                "mapping": PolylineTopologyMap(
                    anchor.entity_id, (0, 3, 2, 1), 4, True
                ).to_mapping(),
            },
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()},
        ],
    }
    with pytest.raises(ValidationError, match="替换|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=75)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 76
    arrays = services.kernel.associative_arrays
    original_sketches = services.kernel.sketches
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=76)
    assert services.kernel.sketches[0].entities[4] == entities[4]
    extra = services.kernel.sketches[0].entities[5]
    assert isinstance(extra, PolylineEntity)
    assert extra.point_ids == (entities[5].point_ids[0], *reversed(entities[5].point_ids[1:]))
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    updated_extra = services.kernel.drawing_datum_identifiers[1]
    assert updated_extra.attachment is not None and updated_extra.attachment.reference.index == 3
    assert updated_extra.target_mm == pytest.approx(extra_datum.target_mm)
    assert (
        updated_frame.leader_attachment is not None
        and updated_frame.leader_attachment.reference.index == 3
    )
    assert updated_frame.leader_target_mm == pytest.approx(datum.target_mm)
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    assert services.kernel.drawing_datum_identifiers == (updated, updated_extra)
    if with_base:
        changed_base = next(
            array.base_point
            for array in services.kernel.associative_arrays
            if array.base_point is not None
        )
        assert (
            changed_base is not None
            and changed_base.reference is not None
            and changed_base.reference.index == 3
        )
    else:
        assert services.kernel.associative_arrays == arrays
    final_arrays = services.kernel.associative_arrays
    loaded.bus.undo_operation()
    assert services.kernel.sketches == original_sketches
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated, updated_extra)
    path = tmp_path / "unchanged-replacement-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated, updated_extra)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)
    assert reopened.kernel.associative_arrays == final_arrays
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)
        assert reopened.kernel.cross_sketch_tangencies == (relation,)


def test_mixed_reorder_preserves_unrelated_extra_tangency(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    with_base = True
    with_tangency = True
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in (
            (uuid4().hex, (0, 0)),
            (uuid4().hex, (30, 0)),
            (uuid4().hex, (0, 20)),
            (uuid4().hex, (0, 40)),
            (uuid4().hex, (60, 0)),
            (uuid4().hex, (0, 20)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
        extra_outputs=(ArrayExtraOutput(refs[4], refs[5], refs[0], 1, 0),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[2], reference=SketchGeometryReference(refs[2].entity_id, "vertex", 1)
        )
        if with_base
        else None,
    )
    for array in (b, a):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = None
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (5, 22), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, entities[5].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (5, 46), (2.5, 40), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(entities[1].point_ids[0], *reversed(entities[1].point_ids[1:])),
    )
    revised = replace(sketch, entities=(entities[0], source, *entities[2:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(source.entity_id, (0, 3, 2, 1), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="替换|关联|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=75)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 76
    arrays = services.kernel.associative_arrays
    original_sketches = services.kernel.sketches
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=76)
    assert services.kernel.sketches[0].entities[4:] == entities[4:]
    updated = services.kernel.drawing_datum_identifiers[0]
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert (
        updated_frame.leader_attachment is not None
        and updated_frame.leader_attachment.reference.index == 3
    )
    assert updated_frame.leader_target_mm == pytest.approx(datum.target_mm)
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    assert services.kernel.drawing_datum_identifiers == (updated,)
    if with_base:
        changed_base = next(
            array.base_point
            for array in services.kernel.associative_arrays
            if array.base_point is not None
        )
        assert (
            changed_base is not None
            and changed_base.reference is not None
            and changed_base.reference.index == 3
        )
    else:
        assert services.kernel.associative_arrays == arrays
    final_arrays = services.kernel.associative_arrays
    loaded.bus.undo_operation()
    assert services.kernel.sketches == original_sketches
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.redo_operation()
    assert services.kernel.drawing_datum_identifiers == (updated,)
    path = tmp_path / "unchanged-replacement-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)
    assert reopened.kernel.associative_arrays == final_arrays
    if relation is not None:
        assert services.kernel.cross_sketch_tangencies == (relation,)
        assert reopened.kernel.cross_sketch_tangencies == (relation,)


def test_converging_generated_anchor_and_replacement_reorders_replay(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    positions = ((0, 0), (10, 0), (20, 0), (60, 0), (70, 0), (20, 20), (20, 40))
    entities = tuple(
        PolylineEntity(
            identity,
            ((x, y), (x + 6, y), (x + 6, y + 6), (x, y + 6)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        for identity, (x, y) in ((uuid4().hex, point) for point in positions)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)

    def horizontal(source: ArrayEntityRef, target: ArrayEntityRef) -> AssociativeRectArray:
        return AssociativeRectArray(
            uuid4().hex, sketch.frame, 1, 2, 0, 10, (source,), (ArrayMember(source, target, 0, 1),)
        )

    a0, a1, b0 = (
        horizontal(refs[0], refs[1]),
        horizontal(refs[1], refs[2]),
        horizontal(refs[3], refs[4]),
    )
    join = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[5], 1, 0, replacement=ArrayReplacement(refs[4])),),
        base_point=ArrayBasePoint(
            source=refs[2], reference=SketchGeometryReference(refs[2].entity_id, "vertex", 1)
        ),
    )
    last = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[5],), (ArrayMember(refs[5], refs[6], 1, 0),)
    )
    for array in (join, last, a1, b0, a0):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(entities[6].entity_id, "segment", 0), 0.25, 4
    )
    datum = DatumIdentifier(uuid4().hex, "A", (25, 46), (21.5, 40), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (30, 46),
        leader_target_mm=datum.target_mm,
        leader_attachment=attachment,
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )

    def reverse(item: PolylineEntity) -> PolylineEntity:
        return replace(
            item,
            points_mm=(item.points_mm[0], *reversed(item.points_mm[1:])),
            point_ids=(item.point_ids[0], *reversed(item.point_ids[1:])),
        )

    revised = replace(
        sketch,
        entities=tuple(
            reverse(item) if idx in (0, 3) else item for idx, item in enumerate(entities)
        ),
    )
    state = revised.to_state_mapping()
    mappings = [
        PolylineTopologyMap(entities[idx].entity_id, (0, 3, 2, 1), 4, True) for idx in (0, 3)
    ]
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": item.to_mapping()} for item in mappings
        ],
    }
    with pytest.raises(ValidationError, match="关联|顺序|重复|重绑定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=74)
    records, _, version = app.exact_attached_polyline_reorder_maps(services, (sketch,), (revised,))
    assert records == tuple(params["polyline_topology_maps"]) and version == 75
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=75)
    updated, updated_frame = (
        services.kernel.drawing_datum_identifiers[0],
        services.kernel.drawing_tolerance_frames[0],
    )
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert (
        updated_frame.leader_attachment is not None
        and updated_frame.leader_attachment.reference.index == 3
    )
    assert updated.target_mm == pytest.approx(datum.target_mm)
    updated_join = next(
        array for array in services.kernel.associative_arrays if array.array_id == join.array_id
    )
    assert (
        updated_join.base_point is not None
        and updated_join.base_point.reference is not None
        and updated_join.base_point.reference.index == 3
    )
    for idx in (1, 2, 4, 5, 6):
        item = services.kernel.sketches[0].entities[idx]
        assert isinstance(item, PolylineEntity)
        assert item.point_ids == (
            entities[idx].point_ids[0],
            *reversed(entities[idx].point_ids[1:]),
        )
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.redo_operation()
    path = tmp_path / "converging-chain.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)
    assert reopened.kernel.associative_arrays == services.kernel.associative_arrays


def test_array_member_tangency_rebinds_exact_reorder_and_replays(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(uuid4().hex, ((0, y), (10, y), (10, y + 10), (0, y + 10)), closed=True)
        for y in (0, 20, 40)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    for source, target in zip(refs[:-1], refs[1:], strict=True):
        array = AssociativeRectArray(
            uuid4().hex, sketch.frame, 2, 1, 20, 0, (source,), (ArrayMember(source, target, 1, 0),)
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    circle = CircleEntity(uuid4().hex, (5, 42), 2)
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, other, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketch.sketch_id, entities[2].entity_id, 0),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add",
        {"relation": relation.to_mapping(), "revisions": []},
        "local",
        version=12,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 46),
        (2.5, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[2].entity_id, "segment", 0), 0.25, 4
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    rotated = replace(entities[0], points_mm=(*entities[0].points_mm[1:], entities[0].points_mm[0]))
    revised = replace(sketch, entities=(rotated, *entities[1:]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(entities[0].entity_id, (3, 0, 1, 2), 4, True)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="相切"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=76)
    count, before = loaded.document.command_count, services.kernel.sketches
    altered = replace(relation, branch="line_right")
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                **params,
                "remove_tangencies": [relation.relation_id],
                "cross_tangencies": [altered.to_mapping()],
            },
            "local",
            version=77,
        )
    assert loaded.document.command_count == count and services.kernel.sketches == before
    assert services.kernel.cross_sketch_tangencies == (relation,)
    records, _, selected_version = app.exact_attached_polyline_reorder_maps(
        services, (sketch, other), (revised, other)
    )
    assert records == tuple(params["polyline_topology_maps"]) and selected_version == 77
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=77)
    rebound = services.kernel.cross_sketch_tangencies[0]
    assert rebound == replace(relation, first=replace(relation.first, segment_index=3))
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    loaded.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.redo_operation()
    path = tmp_path / "array-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.cross_sketch_tangencies == (rebound,)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)


def test_cross_sketch_array_reorder_rebinds_multiple_member_tangencies(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    curves: list[PolylineEntity] = []
    sketches: list[Sketch] = []
    for y in (0, 20, 40):
        identity = uuid4().hex
        curve = PolylineEntity(
            identity,
            ((0, y), (10, y), (10, y + 10), (0, y + 10)),
            closed=True,
            point_ids=new_curve_point_identities(identity, "polyline", 4),
        )
        sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
        curves.append(curve)
        sketches.append(sketch)
    refs = tuple(
        ArrayEntityRef(s.sketch_id, c.entity_id) for s, c in zip(sketches, curves, strict=True)
    )
    for source, target in zip(refs[:-1], refs[1:], strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            WorkPlaneFrame.xy(),
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0),),
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relations: list[CrossSketchTangency] = []
    for index, y in ((1, 22), (2, 42)):
        circle = CircleEntity(uuid4().hex, (5, y), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketches[index].sketch_id, curves[index].entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_left",
        )
        loaded.bus.execute(
            "drawing.tangency.add",
            {"relation": relation.to_mapping(), "revisions": []},
            "local",
            version=12,
        )
        relations.append(relation)
    layers = services.kernel.drawing_layers.add(SketchLayer("TANGENCY-DATUM"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 46),
        (2.5, 40),
        layer_name="TANGENCY-DATUM",
        attachment=DatumAttachment(
            sketches[2].sketch_id,
            SketchGeometryReference(curves[2].entity_id, "segment", 0),
            0.25,
            4,
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    old = curves[0]
    rotated = replace(
        old,
        points_mm=(*old.points_mm[1:], old.points_mm[0]),
        point_ids=(*old.point_ids[1:], old.point_ids[0]),
    )
    revised = replace(sketches[0], entities=(rotated,))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(old.entity_id, (3, 0, 1, 2), 4, True)
    revisions: list[dict[str, object]] = [
        {
            "sketch_id": sketches[0].sketch_id,
            "base_state_sha256": sketches[0].local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    params: dict[str, object] = {
        "revisions": revisions,
        "polyline_topology_maps": [
            {"sketch_id": sketches[0].sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    locked = replace(
        layers,
        layers=tuple(
            replace(layer, locked=True) if layer.name == "TANGENCY-DATUM" else layer
            for layer in layers.layers
        ),
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    before = services.kernel.sketches
    before_arrays = services.kernel.associative_arrays
    revisions[0]["base_state_sha256"] = next(
        item for item in before if item.sketch_id == sketches[0].sketch_id
    ).local_state_digest()
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="锁定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=77)
    with pytest.raises(ValidationError, match="锁定"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=78)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before
    assert services.kernel.associative_arrays == before_arrays
    assert set(services.kernel.cross_sketch_tangencies) == set(relations)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    revisions[0]["base_state_sha256"] = next(
        item for item in services.kernel.sketches if item.sketch_id == sketches[0].sketch_id
    ).local_state_digest()
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=77)
    expected = tuple(
        sorted(
            (replace(r, first=replace(r.first, segment_index=3)) for r in relations),
            key=lambda r: r.relation_id,
        )
    )
    assert services.kernel.cross_sketch_tangencies == expected
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    for index in (1, 2):
        item = next(
            s for s in services.kernel.sketches if s.sketch_id == sketches[index].sketch_id
        ).entities[0]
        assert isinstance(item, PolylineEntity)
        assert item.point_ids == (*curves[index].point_ids[1:], curves[index].point_ids[0])
    loaded.bus.undo_operation()
    assert set(services.kernel.cross_sketch_tangencies) == set(relations)
    loaded.bus.redo_operation()
    path = tmp_path / "cross-sketch-array-tangencies.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.cross_sketch_tangencies == expected
    assert reopened.kernel.drawing_datum_identifiers == (updated,)


def test_chain_reverses_member_tangency_and_replays(tmp_path: Path) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    has_ids = True
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    entities = tuple(
        PolylineEntity(uuid4().hex, ((0, y), (10, y), (10, y + 10))) for y in (0, 20, 40, 60)
    )
    if has_ids:
        entities = tuple(
            replace(item, point_ids=new_curve_point_identities(item.entity_id, "polyline", 3))
            for item in entities
        )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    for source, target in zip(refs[:-1], refs[1:], strict=True):
        array = AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (source,),
            (ArrayMember(source, target, 1, 0),),
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "vertex", 0)
            )
            if source in refs[1:]
            else None,
        )
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    circle = CircleEntity(uuid4().hex, (5, 42), 2)
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, other, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketch.sketch_id, entities[2].entity_id, 0),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add",
        {"relation": relation.to_mapping(), "revisions": []},
        "local",
        version=12,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (5, 45),
        (2.5, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[2].entity_id, "segment", 0), 0.25, 2
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (5, 66),
        leader_target_mm=(2.5, 60),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "segment", 0), 0.25, 2
        ),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
        "local",
    )
    reversed_source = replace(
        entities[0],
        points_mm=tuple(reversed(entities[0].points_mm)),
        point_ids=tuple(reversed(entities[0].point_ids)),
    )
    state = replace(sketch, entities=(reversed_source, *entities[1:])).to_state_mapping()
    mapping = PolylineTopologyMap(entities[0].entity_id, (2, 1, 0), 3, False)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    before = services.kernel.sketches
    before_arrays = services.kernel.associative_arrays
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="相切"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=70)
    with pytest.raises(ValidationError, match="相切"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=77)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == before
    assert services.kernel.associative_arrays == before_arrays
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_tolerance_frames == (frame,)

    loaded.bus.execute("drawing.sketch.revise", params, "local", version=78)
    rebound = services.kernel.cross_sketch_tangencies[0]
    assert rebound == replace(
        relation, first=replace(relation.first, segment_index=1), branch="line_right"
    )
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 1
    assert updated.target_mm == pytest.approx(datum.target_mm)
    updated_frame = services.kernel.drawing_tolerance_frames[0]
    assert (
        updated_frame.leader_attachment is not None
        and updated_frame.leader_attachment.reference.index == 1
    )
    loaded.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.redo_operation()
    path = tmp_path / "reverse-array-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.cross_sketch_tangencies == (rebound,)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
    assert reopened.kernel.drawing_tolerance_frames == (updated_frame,)


def test_array_reversed_arc_retains_tangent_endpoint_and_branch(tmp_path: Path) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    curves = tuple(PolylineEntity(uuid4().hex, ((0, y), (10, y)), bulges=(1.0,)) for y in (0, 20))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), curves)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source, target = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in curves)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (source,), (ArrayMember(source, target, 1, 0),)
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    line = LineEntity(uuid4().hex, (0, 15), (0, 25))
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, other, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketch.sketch_id, curves[1].entity_id, 0),
        CrossSketchRef(other.sketch_id, line.entity_id),
        "line_right",
        first_endpoint="start",
    )
    loaded.bus.execute(
        "drawing.tangency.add",
        {"relation": relation.to_mapping(), "revisions": []},
        "local",
        version=12,
    )
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(curves[1].entity_id, "segment", 0), 0.25, 1
    )
    point = resolve_attachment_local(attachment, {curves[1].entity_id: curves[1]})
    assert point is not None
    datum = DatumIdentifier(uuid4().hex, "A", (15, 25), point, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    reversed_curve = replace(
        curves[0], points_mm=tuple(reversed(curves[0].points_mm)), bulges=(-1.0,)
    )
    revised = replace(sketch, entities=(reversed_curve, curves[1]))
    state = revised.to_state_mapping()
    mapping = PolylineTopologyMap(curves[0].entity_id, (1, 0), 2, False)
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "polyline_topology_maps": [
            {"sketch_id": sketch.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    with pytest.raises(ValidationError, match="相切"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=77)
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=78)
    rebound = services.kernel.cross_sketch_tangencies[0]
    assert rebound == replace(relation, first_endpoint="end")
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.parameter == pytest.approx(0.75)
    assert updated.target_mm == pytest.approx(point)
    loaded.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.redo_operation()
    path = tmp_path / "reverse-arc-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.cross_sketch_tangencies == (rebound,)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)


def test_frame_leader_arrow_style_is_versioned_and_replays(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, 0),
        leader_arrow_style="closed_filled",
    )
    params = {"add_frames": [frame.to_mapping()]}
    with pytest.raises(ValidationError, match="箭头"):
        loaded.bus.execute("drawing.tolerance.batch", params, "local", version=27)
    legacy_field = dict(frame.to_mapping(), leader_arrow_style="legacy")
    with pytest.raises(ValidationError, match="箭头"):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_frames": [legacy_field]}, "local", version=27
        )
    assert not services.kernel.drawing_tolerance_frames
    loaded.bus.execute("drawing.tolerance.batch", params, "local", version=28)
    assert services.kernel.drawing_tolerance_frames == (frame,)
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_tolerance_frames
    loaded.bus.redo_operation()
    path = tmp_path / "frame-arrow-style.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_tolerance_frames == (frame,)
