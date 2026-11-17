# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Whole-polyline no-trim fillets preserve their tangent sources."""

import math
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    RectangleTransformEvidence,
    validate_tangency_component,
)
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow


def test_polyline_rigid_seed_rejects_deformation() -> None:
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)), bulges=(0.25, 0))
    reference = CrossSketchRef(uuid4().hex, source.entity_id)
    method_name = "_polyline_transform_seed"
    infer = cast(
        "Callable[[CrossSketchRef, PolylineEntity, PolylineEntity], RectangleTransformEvidence | None]",
        getattr(app, method_name),
    )
    rotated = replace(source, points_mm=((3, 2), (3, 12), (-2, 12)))
    mirrored = replace(source, points_mm=((0, 0), (-10, 0), (-10, 5)), bulges=(-0.25, 0))
    assert infer(reference, source, rotated) is not None
    seed = infer(reference, source, mirrored)
    assert seed is not None and seed.reflected
    assert infer(reference, source, replace(rotated, points_mm=((3, 2), (3, 12), (-1, 12)))) is None
    assert infer(reference, source, replace(mirrored, bulges=(0.25, 0))) is None
    straight = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (20, 0)))
    straight_ref = CrossSketchRef(uuid4().hex, straight.entity_id)
    assert (
        infer(straight_ref, straight, replace(straight, points_mm=((0, 0), (0, 10), (0, 20))))
        is None
    )
    assert (
        infer(straight_ref, straight, replace(straight, points_mm=((2, 3), (12, 3), (22, 3))))
        is not None
    )


@pytest.mark.parametrize(
    ("transform", "opposite", "both"),
    [
        ("rotate", False, False),
        ("mirror", False, False),
        ("mirror", True, False),
        ("rotate", False, True),
        ("mirror", False, True),
        ("mirror", True, True),
    ],
)
def test_collinear_polyline_uses_user_transform(
    qtbot: QtBot, tmp_path: Path, transform: str, opposite: bool, both: bool
) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (20, 0)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    frame = (
        WorkPlaneFrame((5, 7, 0), (0, 1, 0), (1, 0, 0), (0, 0, -1))
        if opposite
        else WorkPlaneFrame.xy()
    )
    first = Sketch(uuid4().hex, frame, (source,))
    second = Sketch(uuid4().hex, frame, (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    original = services.kernel.sketches
    count = loaded.document.command_count
    from mycad.core.sketch_edit import mirror_entities

    wrong_target = mirror_entities((source,), (source.entity_id,), (0, 0), (0, 1))[0]
    proposal = (replace(original[0], entities=(wrong_target,)), original[1])
    bad_proof = RectangleTransformEvidence(
        CrossSketchRef(first.sketch_id, source.entity_id), (1, 0, 0, 1, 0, 0)
    )
    with pytest.raises(ValidationError, match="变换依据"):
        app.commit_cross_sketch_edit(
            services,
            loaded,
            original,
            proposal,
            (bad_proof.reference,),
            session_identity=0,
            polyline_transforms=(bad_proof,),
        )
    assert services.kernel.sketches == original and loaded.document.command_count == count
    selected = (source.entity_id, circle.entity_id) if both else (source.entity_id,)
    if transform == "mirror":
        editor.canvas.committed_mirror_requested.emit(selected, (0.0, 0.0), (0.0, 1.0))
    else:
        editor.canvas.committed_rotation_requested.emit(selected, (0.0, 0.0), 90.0)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert loaded.document.command_count == count + 1, editor.status_label.text()
    changed = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert relations[0].branch == ("line_right" if transform == "mirror" else "line_left")
    validate_tangency_component(changed, relations, first.sketch_id)
    moved_circle = next(
        entity
        for sketch in changed
        for entity in sketch.entities
        if entity.entity_id == circle.entity_id
    )
    assert isinstance(moved_circle, CircleEntity)
    x, y, _ = frame.local_to_world(circle.center_mm)
    expected = (-y, x, 0.0) if transform == "rotate" else (-x, y, 0.0)
    assert frame.local_to_world(moved_circle.center_mm) == pytest.approx(expected, abs=1e-5)
    path = tmp_path / "collinear-mirror.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == changed
    reopened.bus.undo()
    assert restored.kernel.sketches == original
    reopened.bus.redo()
    assert restored.kernel.sketches == changed


@pytest.mark.parametrize("both", [False, True])
def test_polyline_arc_and_line_mirror(qtbot: QtBot, tmp_path: Path, both: bool) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0)), bulges=(1.0,))
    line = LineEntity(uuid4().hex, (0, -5), (10, -5))
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    target = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    for sketch in (source, target):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(source.sketch_id, polyline.entity_id, 0),
        CrossSketchRef(target.sketch_id, line.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    original = services.kernel.sketches
    count = loaded.document.command_count
    selected = (polyline.entity_id, line.entity_id) if both else (polyline.entity_id,)
    editor.canvas.committed_mirror_requested.emit(selected, (0.0, 0.0), (0.0, 1.0))
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert loaded.document.command_count == count + 1, editor.status_label.text()
    changed = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert relations[0].branch == "line_right"
    validate_tangency_component(changed, relations, source.sketch_id)
    moved_line = next(
        entity
        for sketch in changed
        for entity in sketch.entities
        if entity.entity_id == line.entity_id
    )
    assert isinstance(moved_line, LineEntity)
    assert moved_line.start_mm == pytest.approx((0, -5), abs=1e-5)
    assert moved_line.end_mm == pytest.approx((-10, -5), abs=1e-5)
    path = tmp_path / "polyline-arc-line-mirror.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == changed
    reopened.bus.undo()
    assert restored.kernel.sketches == original
    reopened.bus.redo()
    assert restored.kernel.sketches == changed


@pytest.mark.parametrize("kind", ["polyline", "rectangle", "line"])
def test_multiple_polyline_mirror_keeps_tangencies(qtbot: QtBot, tmp_path: Path, kind: str) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    if kind == "rectangle":
        first = RectangleEntity(uuid4().hex, (0, 0), (10, -5))
    elif kind == "line":
        first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    else:
        first = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (20, 0)))
    second = PolylineEntity(uuid4().hex, ((0, 4), (10, 4), (20, 4)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    target = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (source, target):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    for entity in (first, second):
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(
                source.sketch_id, entity.entity_id, None if isinstance(entity, LineEntity) else 0
            ),
            CrossSketchRef(target.sketch_id, circle.entity_id),
            "line_left" if entity is first else "line_right",
        )
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    original = services.kernel.sketches
    original_relations = services.kernel.cross_sketch_tangencies
    count = loaded.document.command_count
    if kind == "polyline":
        from mycad.core.sketch_edit import mirror_entities

        ids = (first.entity_id, second.entity_id)
        mirrored = mirror_entities((first, second), ids, (0, 0), (0, 1))
        proposed = (replace(original[0], entities=mirrored), original[1])
        anchors = tuple(CrossSketchRef(source.sketch_id, identity) for identity in ids)
        proofs = (
            RectangleTransformEvidence(anchors[0], (-1, 0, 0, 1, 0, 0)),
            RectangleTransformEvidence(anchors[1], (-1, 0, 0, 1, 1, 0)),
        )
        with pytest.raises(ValidationError, match="变换依据"):
            app.commit_cross_sketch_edit(
                services,
                loaded,
                original,
                proposed,
                anchors,
                session_identity=0,
                polyline_transforms=proofs,
            )
        assert services.kernel.sketches == original and loaded.document.command_count == count
    editor.canvas.committed_mirror_requested.emit(
        (first.entity_id, second.entity_id), (0.0, 0.0), (0.0, 1.0)
    )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert loaded.document.command_count == count + 1, editor.status_label.text()
    changed = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    if kind != "rectangle":
        previous = {item.relation_id: item.branch for item in original_relations}
        assert all(
            item.branch
            == ("line_right" if previous[item.relation_id] == "line_left" else "line_left")
            for item in relations
        )
    moved_circle = next(
        entity
        for sketch in changed
        for entity in sketch.entities
        if entity.entity_id == circle.entity_id
    )
    assert isinstance(moved_circle, CircleEntity)
    assert moved_circle.center_mm == pytest.approx((-5, 2), abs=1e-5)
    validate_tangency_component(changed, relations, source.sketch_id)
    path = tmp_path / "multiple-polyline-mirror.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == changed
    reopened.bus.undo()
    assert restored.kernel.sketches == original
    assert restored.kernel.cross_sketch_tangencies == original_relations
    if kind == "line":
        command = loaded.document.commands[-1]
        assert command.version == 34
        params = deepcopy(command.params)
        with pytest.raises(ValidationError):
            reopened.bus.execute(command.id, params, "local", version=33)
        proofs = cast("list[dict[str, object]]", params["line_transforms"])
        proofs[0]["matrix"] = [1, 0, 0, 1, 0, 0]
        with pytest.raises(ValidationError):
            reopened.bus.execute(command.id, params, "local", version=34)
        assert restored.kernel.sketches == original
        assert restored.kernel.cross_sketch_tangencies == original_relations
    reopened.bus.redo()
    assert restored.kernel.sketches == changed
    assert restored.kernel.cross_sketch_tangencies == relations


@pytest.mark.parametrize("transform", ["rotate", "mirror"])
def test_disconnected_tangent_components_transform_atomically(
    qtbot: QtBot, tmp_path: Path, transform: str
) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (20, 0)))
    line = LineEntity(uuid4().hex, (0, 10), (10, 10))
    circles = (CircleEntity(uuid4().hex, (5, 2), 2), CircleEntity(uuid4().hex, (5, 12), 2))
    sketches = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
        for entity in (polyline, circles[0], line, circles[1])
    )
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    for source_index, target_index, entity, segment in (
        (0, 1, polyline, 0),
        (2, 3, line, None),
    ):
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketches[source_index].sketch_id, entity.entity_id, segment),
            CrossSketchRef(sketches[target_index].sketch_id, circles[source_index // 2].entity_id),
            "line_left",
        )
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    original = services.kernel.sketches
    original_relations = services.kernel.cross_sketch_tangencies
    selected = (polyline.entity_id, line.entity_id)
    count = loaded.document.command_count
    if transform == "mirror":
        from mycad.core.sketch_edit import mirror_entities

        anchor_polyline = CrossSketchRef(sketches[0].sketch_id, polyline.entity_id)
        anchor_line = CrossSketchRef(sketches[2].sketch_id, line.entity_id)
        edited = {
            entity.entity_id: mirror_entities((entity,), (entity.entity_id,), (0, 0), (0, 1))[0]
            for entity in (polyline, line)
        }
        proposed = tuple(
            replace(
                sketch,
                entities=tuple(edited.get(entity.entity_id, entity) for entity in sketch.entities),
            )
            for sketch in original
        )
        good = RectangleTransformEvidence(anchor_polyline, (-1, 0, 0, 1, 0, 0))
        bad = RectangleTransformEvidence(anchor_line, (1, 0, 0, 1, 0, 0))
        with pytest.raises(ValidationError, match="变换依据"):
            app.commit_cross_sketch_edit(
                services,
                loaded,
                original,
                proposed,
                (anchor_polyline, anchor_line),
                session_identity=0,
                polyline_transforms=(good,),
                line_transforms=(bad,),
            )
        assert services.kernel.sketches == original
        assert services.kernel.cross_sketch_tangencies == original_relations
        assert loaded.document.command_count == count
    if transform == "rotate":
        editor.canvas.committed_rotation_requested.emit(selected, (0.0, 0.0), 90.0)
    else:
        editor.canvas.committed_mirror_requested.emit(selected, (0.0, 0.0), (0.0, 1.0))
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert loaded.document.command_count == count + 1, editor.status_label.text()
    changed, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    for source_index in (0, 2):
        validate_tangency_component(changed, relations, sketches[source_index].sketch_id)
    for circle in circles:
        moved = next(
            entity
            for sketch in changed
            for entity in sketch.entities
            if entity.entity_id == circle.entity_id
        )
        assert isinstance(moved, CircleEntity)
        x, y = circle.center_mm
        expected = (-y, x) if transform == "rotate" else (-x, y)
        assert moved.center_mm == pytest.approx(expected, abs=1e-5)
    path = tmp_path / "disconnected-components.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == changed
    reopened.bus.undo()
    assert restored.kernel.sketches == original
    assert restored.kernel.cross_sketch_tangencies == original_relations
    reopened.bus.redo()
    assert restored.kernel.sketches == changed
    assert restored.kernel.cross_sketch_tangencies == relations


@pytest.mark.parametrize(
    ("transform", "two_steps"), [("rotate", False), ("mirror", False), ("mirror", True)]
)
def test_mixed_draft_and_saved_polyline_tangency_transform(
    qtbot: QtBot, tmp_path: Path, transform: str, two_steps: bool
) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (20, 0)))
    linked = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (linked,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, linked.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    draft = CircleEntity(uuid4().hex, (30, 30), 3)
    assert editor.canvas.replace_draft_entities((draft,))
    before = services.kernel.sketches
    selected = (source.entity_id, draft.entity_id)
    if transform == "mirror":
        editor.canvas.committed_mirror_requested.emit(selected, (0.0, 0.0), (0.0, 1.0))
    else:
        editor.canvas.committed_rotation_requested.emit(selected, (0.0, 0.0), 90.0)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert editor.canvas.mixed_move is not None, editor.status_label.text()
    provisional = editor.canvas.mixed_move
    draft_after = tuple(editor.canvas.entities)
    assert services.kernel.sketches == before
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.mixed_move is None
    assert editor.canvas.redo_last_operation()
    assert editor.canvas.mixed_move == provisional
    assert tuple(editor.canvas.entities) == draft_after
    if two_steps:
        editor.canvas.committed_move_requested.emit(selected, (2.0, 1.0))
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert editor.canvas.mixed_move is not None, editor.status_label.text()
        moved = editor.canvas.mixed_move
        assert moved != provisional, editor.status_label.text()
        assert editor.canvas.undo_last_operation()
        assert editor.canvas.mixed_move == provisional
        assert editor.canvas.redo_last_operation()
        assert editor.canvas.mixed_move == moved
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    final = services.kernel.sketches
    validate_tangency_component(final, services.kernel.cross_sketch_tangencies, first.sketch_id)
    path = tmp_path / "mixed-polyline-transform.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == final
    if two_steps:
        reopened.bus.undo()
    reopened.bus.undo()
    if transform == "mirror":
        command = next(
            item
            for item in reversed(loaded.document.commands)
            if "polyline_transforms" in item.params
        )
        assert command.version == 33
        params = deepcopy(command.params)
        prior = restored.kernel.sketches
        prior_relations = restored.kernel.cross_sketch_tangencies
        with pytest.raises(ValidationError):
            reopened.bus.execute(command.id, params, "local", version=32)
        proofs = cast("list[dict[str, object]]", params["polyline_transforms"])
        proofs[0]["matrix"] = [1, 0, 0, 1, 0, 0]
        with pytest.raises(ValidationError):
            reopened.bus.execute(command.id, params, "local", version=33)
        assert restored.kernel.sketches == prior
        assert restored.kernel.cross_sketch_tangencies == prior_relations
    reopened.bus.undo()
    assert restored.kernel.sketches == before
    reopened.bus.redo()
    reopened.bus.redo()
    if two_steps:
        reopened.bus.redo()
    assert restored.kernel.sketches == final


@pytest.mark.parametrize(
    ("transform", "reverse", "curved", "free_target", "free_source", "two_steps", "second_mirror"),
    [
        ("rotate", False, False, False, False, False, False),
        ("mirror", False, False, False, False, False, False),
        ("mirror", True, False, False, False, False, False),
        ("mirror", True, True, False, False, False, False),
        ("mirror", False, False, True, False, False, False),
        ("mirror", True, False, False, True, False, False),
        ("mirror", False, False, False, False, True, False),
        ("mirror", False, False, False, False, True, True),
    ],
)
def test_mixed_pending_polyline_tangency_transform(
    qtbot: QtBot,
    tmp_path: Path,
    transform: str,
    reverse: bool,
    curved: bool,
    free_target: bool,
    free_source: bool,
    two_steps: bool,
    second_mirror: bool,
) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    polyline = (
        PolylineEntity(uuid4().hex, ((0, 0), (10, 0)), bulges=(1,))
        if curved
        else PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (20, 0)))
    )
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    source = (
        LineEntity(uuid4().hex, (0, -5), (10, -5)) if curved else circle if reverse else polyline
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    unrelated_saved = LineEntity(uuid4().hex, (30, 30), (40, 30))
    if free_source:
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (unrelated_saved,)),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    draft = polyline if reverse else circle
    unrelated = CircleEntity(uuid4().hex, (30, 30), 3)
    assert editor.canvas.replace_draft_entities((draft, unrelated) if free_target else (draft,))
    pair = (
        source.entity_id if reverse else SketchGeometryReference(source.entity_id, "segment", 0),
        SketchGeometryReference(draft.entity_id, "segment", 0) if reverse else draft.entity_id,
    )
    editor.canvas.pending_cross_tangencies = [pair]
    selected = (
        unrelated_saved.entity_id if free_source else source.entity_id,
        unrelated.entity_id if free_target else draft.entity_id,
    )
    if transform == "mirror":
        editor.canvas.committed_mirror_requested.emit(selected, (0.0, 0.0), (0.0, 1.0))
    else:
        editor.canvas.committed_rotation_requested.emit(selected, (0.0, 0.0), 90.0)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert editor.canvas.mixed_move is not None, editor.status_label.text()
    assert len(editor.canvas.pending_cross_tangencies) == 1
    provisional = editor.canvas.mixed_move
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.pending_cross_tangencies == [pair]
    assert editor.canvas.redo_last_operation()
    assert editor.canvas.mixed_move == provisional
    assert len(editor.canvas.pending_cross_tangencies) == 1
    if two_steps:
        if second_mirror:
            editor.canvas.committed_mirror_requested.emit(selected, (0.0, 0.0), (1.0, 0.0))
        else:
            editor.canvas.committed_move_requested.emit(selected, (2.0, 1.0))
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert editor.canvas.mixed_move is not None, editor.status_label.text()
        moved = editor.canvas.mixed_move
        assert moved != provisional, editor.status_label.text()
        assert len(editor.canvas.pending_cross_tangencies) == 1
        assert editor.canvas.undo_last_operation()
        assert editor.canvas.mixed_move == provisional
        assert editor.canvas.redo_last_operation()
        assert editor.canvas.mixed_move == moved
        if second_mirror:
            extra = CircleEntity(uuid4().hex, (40, 40), 1)
            assert editor.canvas.replace_draft_entities((*editor.canvas.entities, extra))
            history = editor.canvas.mixed_move_timeline_with_transforms()
            assert sum(bool(proofs) for _saved, _draft, _pairs, _arrays, proofs in history) == 2
            assert editor.canvas.undo_last_operation()
            assert editor.canvas.mixed_move == moved
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    final = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 1
    assert relations[0].branch == (
        "line_right" if transform == "mirror" and not second_mirror else "line_left"
    )
    validate_tangency_component(final, relations, saved.sketch_id)
    if free_target:
        moved = next(
            entity
            for sketch in final
            for entity in sketch.entities
            if entity.entity_id == draft.entity_id
        )
        assert isinstance(moved, CircleEntity)
        assert moved.center_mm == pytest.approx((-5, 2), abs=1e-5)
    if free_source:
        moved = next(
            entity
            for sketch in final
            for entity in sketch.entities
            if entity.entity_id == source.entity_id
        )
        assert isinstance(moved, CircleEntity)
        assert moved.center_mm == pytest.approx((-5, 2), abs=1e-5)
    path = tmp_path / "mixed-pending-polyline.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == final
    if two_steps:
        reopened.bus.undo()
    reopened.bus.undo()
    assert restored.kernel.cross_sketch_tangencies[0].branch == "line_left"
    assert restored.kernel.cross_sketch_tangencies[0].relation_id == relations[0].relation_id
    reopened.bus.redo()
    if two_steps:
        reopened.bus.redo()
    assert restored.kernel.sketches == final
    assert restored.kernel.cross_sketch_tangencies == relations


@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize(("closed", "arc_count"), [(False, 2), (True, 4)])
def test_whole_polyline_notrim_creates_tangencies_and_replays(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    saved: bool,
    closed: bool,
    arc_count: int,
) -> None:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    points = (
        ((0, 0), (20, 0), (20, 10), (0, 10)) if closed else ((0, 0), (10, 0), (10, 10), (20, 10))
    )
    source = PolylineEntity(uuid4().hex, points, closed=closed)
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    if saved:
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,)),
            session_identity=0,
        )
        editor.set_context_sketches(services.kernel.sketches)
    else:
        assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert len([entity for entity in canvas.entities if isinstance(entity, ArcEntity)]) == arc_count
    if saved:
        assert len(canvas.pending_cross_tangencies) == 2 * arc_count
    else:
        assert (
            len([relation for relation in canvas.constraints if relation.kind == "tangent"])
            == 2 * arc_count
        )
    rounded_entities = tuple(canvas.entities)
    rounded_constraints = tuple(canvas.constraints)
    pending = tuple(canvas.pending_cross_tangencies)
    assert canvas.undo_last_operation()
    assert not any(isinstance(entity, ArcEntity) for entity in canvas.entities)
    assert not canvas.pending_cross_tangencies
    assert canvas.redo_last_operation()
    assert tuple(canvas.entities) == rounded_entities
    assert tuple(canvas.constraints) == rounded_constraints
    assert tuple(canvas.pending_cross_tangencies) == pending
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    sketches = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == (2 * arc_count if saved else 0)
    if saved:
        validate_tangency_component(sketches, relations, relations[0].first.sketch_id)
        current = window.active_sketch_dialog()
        assert current is not None
        count = len(loaded.document.commands)
        current.canvas.committed_move_requested.emit((source.entity_id,), (0.0, 1.0))
        qtbot.waitUntil(
            lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
        )
        moved = services.kernel.sketches
        assert moved != sketches
        validate_tangency_component(moved, relations, relations[0].first.sketch_id)
        window.request_undo()
        qtbot.waitUntil(
            lambda: not unit.is_busy and services.kernel.sketches == sketches, timeout=10000
        )
        for transform in ("rotate", "mirror"):
            current = window.active_sketch_dialog()
            assert current is not None
            count = loaded.document.command_count
            if transform == "rotate":
                current.canvas.committed_rotation_requested.emit(
                    (source.entity_id,), (0.0, 0.0), 30.0
                )
            else:
                current.canvas.committed_mirror_requested.emit(
                    (source.entity_id,), (0.0, 0.0), (0.0, 1.0)
                )
            qtbot.waitUntil(
                lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000
            )
            assert loaded.document.command_count == count + 1, current.status_label.text()
            changed_relations = services.kernel.cross_sketch_tangencies
            validate_tangency_component(
                services.kernel.sketches, changed_relations, changed_relations[0].first.sketch_id
            )
            if transform == "mirror":
                command = loaded.document.commands[-1]
                assert command.version == 33
                path = tmp_path / "mirror-polyline.my2d"
                save_document(loaded.document, path)
                restored = app.build_app(discoverers=[])
                reopened = app.open_app_document(restored, path)
                assert restored.kernel.sketches == services.kernel.sketches
                assert restored.kernel.cross_sketch_tangencies == changed_relations
                reopened.bus.undo()
                assert restored.kernel.sketches == sketches
                assert restored.kernel.cross_sketch_tangencies == relations
                params = deepcopy(command.params)
                with pytest.raises(ValidationError):
                    reopened.bus.execute(command.id, params, "local", version=32)
                altered = deepcopy(command.params)
                altered_relations = cast("list[dict[str, object]]", altered["cross_tangencies"])
                branch = altered_relations[0]["branch"]
                altered_relations[0]["branch"] = (
                    "line_right" if branch == "line_left" else "line_left"
                )
                with pytest.raises(ValidationError):
                    reopened.bus.execute(command.id, altered, "local", version=33)
                proofs = cast("list[dict[str, object]]", params["polyline_transforms"])
                proofs[0]["matrix"] = [1, 0, 0, 1, 0, 0]
                with pytest.raises(ValidationError):
                    reopened.bus.execute(command.id, params, "local", version=33)
                assert restored.kernel.sketches == sketches
                assert restored.kernel.cross_sketch_tangencies == relations
                reopened.bus.redo()
                assert restored.kernel.cross_sketch_tangencies == changed_relations
            window.request_undo()
            qtbot.waitUntil(
                lambda: not unit.is_busy and services.kernel.sketches == sketches, timeout=10000
            )
    path = tmp_path / "whole-polyline-notrim.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert (
        restored.kernel.sketches == sketches
        and restored.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert not restored.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert (
        restored.kernel.sketches == sketches
        and restored.kernel.cross_sketch_tangencies == relations
    )


def test_whole_polyline_notrim_ambiguous_sources_do_not_guess(qtbot: QtBot) -> None:
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    source = PolylineEntity(
        uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0), (10, 0), (10, 10))
    )
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    arcs = [entity for entity in canvas.entities if isinstance(entity, ArcEntity)]
    assert arcs and "来源不唯一" in canvas.message
    duplicate = [arc for arc in arcs if arc.center_mm == pytest.approx((8, 2))]
    assert len(duplicate) == 2
    assert not any(
        ref.entity_id in {arc.entity_id for arc in duplicate}
        for relation in canvas.constraints
        for ref in relation.references
    )


@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("both_arcs", [False, True])
def test_whole_polyline_curved_notrim_creates_tangencies(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    saved: bool,
    reverse: bool,
    both_arcs: bool,
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import LineEntity

    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    points = (
        ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0))
        if both_arcs
        else ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0))
    )
    quarter = 2**0.5 - 1
    bulges = (
        ((-quarter, -quarter) if reverse else (quarter, quarter))
        if both_arcs
        else ((-quarter, 0) if reverse else (0, quarter))
    )
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse else points,
        bulges=bulges,
    )
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    if saved:
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,)),
            session_identity=0,
        )
        editor.set_context_sketches(services.kernel.sketches)
    else:
        assert canvas.replace_draft_entities((source,))
    for value in ("FILLET", "R", "1", "T", "N", "P"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    first = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)[0]
    if isinstance(first, LineEntity):
        pick = (
            (first.start_mm[0] + first.end_mm[0]) / 2,
            (first.start_mm[1] + first.end_mm[1]) / 2,
        )
    else:
        angle = math.radians(first.start_angle_deg + first.sweep_angle_deg / 2)
        pick = (
            first.center_mm[0] + first.radius_mm * math.cos(angle),
            first.center_mm[1] + first.radius_mm * math.sin(angle),
        )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(pick))
    assert len([entity for entity in canvas.entities if isinstance(entity, ArcEntity)]) == 1
    assert len(canvas.pending_cross_tangencies) == (2 if saved else 0)
    assert len([item for item in canvas.constraints if item.kind == "tangent"]) == (
        0 if saved else 2
    )
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    if saved:
        relations = services.kernel.cross_sketch_tangencies
        assert len(relations) == 2
        original = services.kernel.sketches
        validate_tangency_component(original, relations, relations[0].first.sketch_id)
        current = window.active_sketch_dialog()
        assert current is not None
        count = loaded.document.command_count
        current.canvas.committed_move_requested.emit((source.entity_id,), (0.0, 1.0))
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert loaded.document.command_count == count + 1, current.status_label.text()
        moved = services.kernel.sketches
        assert moved != original
        validate_tangency_component(moved, relations, relations[0].first.sketch_id)
        window.request_undo()
        qtbot.waitUntil(
            lambda: not unit.is_busy and services.kernel.sketches == original, timeout=10000
        )
        if both_arcs and not reverse:
            for transform in ("rotate", "mirror"):
                current = window.active_sketch_dialog()
                assert current is not None
                count = loaded.document.command_count
                if transform == "rotate":
                    current.canvas.committed_rotation_requested.emit(
                        (source.entity_id,), (0.0, 0.0), 30.0
                    )
                else:
                    current.canvas.committed_mirror_requested.emit(
                        (source.entity_id,), (0.0, 0.0), (0.0, 1.0)
                    )
                qtbot.waitUntil(
                    lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000
                )
                assert loaded.document.command_count == count + 1, current.status_label.text()
                moved_relations = services.kernel.cross_sketch_tangencies
                validate_tangency_component(
                    services.kernel.sketches, moved_relations, moved_relations[0].first.sketch_id
                )
                window.request_undo()
                qtbot.waitUntil(
                    lambda: not unit.is_busy and services.kernel.sketches == original, timeout=10000
                )
        path = tmp_path / "whole-polyline-curved.my2d"
        save_document(loaded.document, path)
        restored = app.build_app(discoverers=[])
        app.open_app_document(restored, path)
        assert restored.kernel.sketches == original
        assert restored.kernel.cross_sketch_tangencies == relations


def test_whole_polyline_notrim_respects_disabled_inference(qtbot: QtBot) -> None:
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert canvas.replace_draft_entities((source,))
    for value in ("FILLET", "R", "2", "T", "N", "P"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert len([entity for entity in canvas.entities if isinstance(entity, ArcEntity)]) == 1
    assert not canvas.constraints and not canvas.pending_cross_tangencies
    assert "未自动建立相切" not in canvas.message


def test_whole_polyline_notrim_keeps_arc_coincident_with_unrelated_old_arc(qtbot: QtBot) -> None:
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    source = PolylineEntity(
        uuid4().hex,
        ((2, 0), (0, -2), (2, 10), (2, -2), (-10, -2)),
        bulges=(1 - 2**0.5, 0, 0, 0),
    )
    assert canvas.replace_draft_entities((source,))
    for value in ("FILLET", "R", "2", "T", "N", "P"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-5, -2)))
    arcs = [entity for entity in canvas.entities if isinstance(entity, ArcEntity)]
    assert canvas.entities[0] == source and len(arcs) == 1
    assert arcs[0].center_mm == pytest.approx((0, 0)) and arcs[0].radius_mm == pytest.approx(2)


def test_whole_fillet_index_matches_exhaustive_tangent_search() -> None:
    from typing import Protocol, cast

    from mycad.core.cross_sketch_tangency import arc_tangent_endpoint
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_notrim
    from mycad.core.sketch import LineEntity
    from mycad.ui import sketch_editor

    class SourceMatcher(Protocol):
        def __call__(
            self,
            segments: tuple[LineEntity | ArcEntity, ...],
            arcs: tuple[ArcEntity, ...],
            *,
            closed: bool,
        ) -> tuple[tuple[int, int] | None, ...]: ...

    matcher_name = "_whole_fillet_source_pairs"
    match_sources = cast("SourceMatcher", getattr(sketch_editor, matcher_name))

    quarter = 2**0.5 - 1
    cases = (
        (PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10))), 2.0),
        (
            PolylineEntity(uuid4().hex, ((1e8, 1e8), (1e8 + 10, 1e8), (1e8 + 10, 1e8 + 10))),
            2.0,
        ),
        (PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 10), (0, 10)), closed=True), 2.0),
        (PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (5, 5)), bulges=(0, quarter)), 1.0),
        (PolylineEntity(uuid4().hex, ((5, 5), (10, 0), (0, 0)), bulges=(-quarter, 0)), 1.0),
        (
            PolylineEntity(uuid4().hex, ((5, -5), (10, 0), (15, 5)), bulges=(quarter, quarter)),
            1.0,
        ),
        (
            PolylineEntity(uuid4().hex, ((15, 5), (10, 0), (5, -5)), bulges=(-quarter, -quarter)),
            1.0,
        ),
        (
            PolylineEntity(
                uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0), (10, 0), (10, 10))
            ),
            2.0,
        ),
    )
    for source, radius in cases:
        count = len(source.points_mm) if source.closed else len(source.points_mm) - 1
        segments = polyline_curve_segments(
            source.points_mm, source.bulges or (0.0,) * count, source.closed, source.entity_id
        )
        arcs = polyline_fillet_notrim(source, radius)
        expected: list[tuple[int, int] | None] = []
        for arc in arcs:
            matches: list[tuple[int, int]] = []
            for first in range(count if source.closed else count - 1):
                second = (first + 1) % count
                if not tangent_on_curves(segments[first], arc) or not tangent_on_curves(
                    segments[second], arc
                ):
                    continue
                try:
                    distinct = arc_tangent_endpoint(arc, segments[first]) != arc_tangent_endpoint(
                        arc, segments[second]
                    )
                except ValueError:
                    continue
                if distinct:
                    matches.append((first, second))
            expected.append(matches[0] if len(matches) == 1 else None)
        assert match_sources(segments, arcs, closed=source.closed) == tuple(expected)
