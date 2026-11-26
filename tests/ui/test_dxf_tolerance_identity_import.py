# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF import remaps annotation attachments when the sketch ID already exists."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.geometric_tolerance import (
    AnnotationAttachment,
    DatumAttachment,
    DatumIdentifier,
    DatumReference,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.core.geometric_tolerance_topology import new_curve_point_identities
from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf
from mycad.ui.main_window import MainWindow


def test_import_duplicate_sketch_remaps_datum_and_frame_attachments(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(source.sketch_id, SketchGeometryReference(line.entity_id, "start"))
    datum = DatumIdentifier(uuid4().hex, "A", (3, 4), (0, 0), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (5, 5),
        leader_target_mm=(0, 0),
        leader_attachment=attachment,
        leader_anchor_offset=(0, -2),
    )
    path = tmp_path / "same-sketch.dxf"
    write_sketches_dxf((source,), path, datum_identifiers=(datum,), tolerance_frames=(frame,))
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    app.commit_new_sketch(services, loaded, source, session_identity=0)

    def accept(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", accept)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(lambda: len(services.kernel.sketches) == 2 and not unit.is_busy, timeout=15000)
    new_id = services.kernel.sketches[1].sketch_id
    assert new_id != source.sketch_id
    datum_attachment = services.kernel.drawing_datum_identifiers[0].attachment
    frame_attachment = services.kernel.drawing_tolerance_frames[0].leader_attachment
    assert datum_attachment is not None and datum_attachment.sketch_id == new_id
    assert frame_attachment is not None and frame_attachment.sketch_id == new_id


def test_import_duplicate_sketch_remaps_datum_dimension_attachment(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=20,
        unit="mm",
        position_mm=(0, 5),
    )
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 5),
        annotation_attachment=AnnotationAttachment(
            "sketch_dimension", dimension.constraint_id, (0, 0), source.sketch_id
        ),
    )
    path = tmp_path / "same-sketch-dimension.dxf"
    write_sketches_dxf((source,), path, datum_identifiers=(datum,))
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    app.commit_new_sketch(services, loaded, source, session_identity=0)

    def accept(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", accept)
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(lambda: len(services.kernel.sketches) == 2 and not unit.is_busy, timeout=15000)
    new_sketch = services.kernel.sketches[1]
    annotation = services.kernel.drawing_datum_identifiers[0].annotation_attachment
    assert annotation is not None
    assert annotation.sketch_id == new_sketch.sketch_id
    assert annotation.object_id == new_sketch.constraints[0].constraint_id
    loaded.bus.undo()
    assert not services.kernel.drawing_datum_identifiers
    loaded.bus.redo()
    assert services.kernel.drawing_datum_identifiers[0].annotation_attachment == annotation
    from mycad.core.persistence import save_document

    saved = tmp_path / "dimension-attachment.my2d"
    save_document(loaded.document, saved)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, saved)
    assert reopened.kernel.drawing_datum_identifiers[0].annotation_attachment == annotation


def test_import_same_identity_dxf_twice_preserves_annotations_and_history(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = uuid4().hex
    curve = PolylineEntity(
        identity,
        ((0, 0), (10, 0), (10, 10)),
        point_ids=new_curve_point_identities(identity, "polyline", 3),
    )
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    attachment = DatumAttachment(source.sketch_id, SketchGeometryReference(identity, "vertex", 0))
    datum = DatumIdentifier(uuid4().hex, "A", (3, 4), (0, 0), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum_id=datum.datum_id),)),),
        (5, 5),
        leader_target_mm=(0, 0),
        leader_attachment=attachment,
        leader_anchor_offset=(0, -2),
    )
    path = tmp_path / "repeat.dxf"
    write_sketches_dxf((source,), path, datum_identifiers=(datum,), tolerance_frames=(frame,))
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    previews: list[str] = []
    errors: list[str] = []

    def accept(
        _parent: object, _title: object, message: str, *_args: object
    ) -> QMessageBox.StandardButton:
        previews.append(message)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", accept)
    monkeypatch.setattr(window, "_show_error", errors.append)
    queue = cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])
    queue(window, path, unit_override=None)
    qtbot.waitUntil(lambda: len(services.kernel.sketches) == 1 and not unit.is_busy, timeout=15000)
    queue(window, path, unit_override=None)
    qtbot.waitUntil(
        lambda: (len(services.kernel.sketches) == 2 or bool(errors)) and not unit.is_busy,
        timeout=15000,
    )
    assert not errors, errors
    copied = services.kernel.sketches[1]
    copied_curve = copied.entities[0]
    assert isinstance(copied_curve, PolylineEntity)
    assert copied_curve.entity_id != identity and set(copied_curve.point_ids).isdisjoint(
        curve.point_ids
    )
    copied_datum = services.kernel.drawing_datum_identifiers[1]
    copied_frame = services.kernel.drawing_tolerance_frames[1]
    assert copied_datum.label == "A-2"
    assert copied_datum.attachment is not None
    assert copied_datum.attachment.sketch_id == copied.sketch_id
    assert copied_datum.attachment.reference.entity_id == copied_curve.entity_id
    assert copied_frame.leader_attachment == copied_datum.attachment
    assert copied_frame.rows[0].datums[0].label == copied_datum.label
    assert copied_frame.rows[0].datums[0].datum_id == copied_datum.datum_id
    assert "A-2" in previews[-1]
    window.act_undo.trigger()
    qtbot.waitUntil(lambda: len(services.kernel.sketches) == 1 and not unit.is_busy, timeout=15000)
    window.act_redo.trigger()
    qtbot.waitUntil(lambda: len(services.kernel.sketches) == 2 and not unit.is_busy, timeout=15000)
    assert services.kernel.drawing_datum_identifiers[1] == copied_datum
    from mycad.core.persistence import save_document

    saved = tmp_path / "repeated.my2d"
    save_document(loaded.document, saved)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, saved)
    assert reopened.kernel.drawing_datum_identifiers[1] == copied_datum
    assert reopened.kernel.drawing_tolerance_frames[1] == copied_frame
    exported = tmp_path / "repeated-export.dxf"
    write_sketches_dxf(
        reopened.kernel.sketches,
        exported,
        datum_identifiers=reopened.kernel.drawing_datum_identifiers,
        tolerance_frames=reopened.kernel.drawing_tolerance_frames,
    )
    restored = read_sketch_dxf(exported)
    assert [item.label for item in restored.datum_identifiers] == ["A", "A-2"]
    assert all(item.attachment is not None for item in restored.datum_identifiers)
    assert all(item.leader_attachment is not None for item in restored.tolerance_frames)
    assert [item.rows[0].datums[0].datum_id for item in restored.tolerance_frames] == [
        item.datum_id for item in restored.datum_identifiers
    ]


@pytest.mark.parametrize(("original", "new"), [("A", "B"), ("A1", "b2")])
def test_import_external_datum_rename_preserves_frame_and_undo(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, original: str, new: str
) -> None:
    import ezdxf.filemanagement as filemanagement

    from mycad.core.persistence import save_document

    datum = DatumIdentifier(
        uuid4().hex, original, (10, 20), (10, 10), layout_mode="shared", box_size_mm=(50, 5)
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference(original, datum.datum_id),)),),
        (25, 20),
    )
    path = tmp_path / "renamed-datum.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,), tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    document.blocks[insert.dxf.name].query("TEXT")[0].dxf.text = new
    document.saveas(path)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes
    )
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: bool(services.kernel.drawing_datum_identifiers) and not unit.is_busy, timeout=15000
    )
    restored = services.kernel.drawing_datum_identifiers[0]
    imported_frame = services.kernel.drawing_tolerance_frames[0]
    assert restored.label == new and restored.box_size_mm is not None
    assert imported_frame.rows[0].datums == (DatumReference(original),)
    loaded.bus.undo_operation()
    assert (
        not services.kernel.drawing_datum_identifiers
        and not services.kernel.drawing_tolerance_frames
    )
    loaded.bus.redo_operation()
    saved = tmp_path / "renamed-datum.my2d"
    save_document(loaded.document, saved)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, saved)
    assert reopened.kernel.drawing_datum_identifiers == (restored,)
    assert reopened.kernel.drawing_tolerance_frames == (imported_frame,)


def test_import_cadcraft_edited_datum_and_resave(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.persistence import save_document

    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-datum-renamed.dxf"
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes
    )
    cast("Callable[..., None]", vars(type(window))["_queue_dxf_sketch_import"])(
        window, path, unit_override=None
    )
    qtbot.waitUntil(
        lambda: bool(services.kernel.drawing_datum_identifiers) and not unit.is_busy, timeout=15000
    )
    datum = services.kernel.drawing_datum_identifiers[0]
    frame = services.kernel.drawing_tolerance_frames[0]
    assert datum.label == "B" and frame.rows[0].datums == (DatumReference("A"),)
    loaded.bus.undo_operation()
    assert not services.kernel.drawing_datum_identifiers
    loaded.bus.redo_operation()
    saved = tmp_path / "cadcraft-datum.my2d"
    save_document(loaded.document, saved)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, saved)
    assert reopened.kernel.drawing_datum_identifiers == (datum,)
    assert reopened.kernel.drawing_tolerance_frames == (frame,)
