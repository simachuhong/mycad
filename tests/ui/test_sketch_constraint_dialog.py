# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Constraint previews are visible and require a separate confirmation."""

from __future__ import annotations

import math
from dataclasses import replace
from functools import partial
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from pytestqt.qtbot import QtBot

from mycad.app import build_app, commit_new_sketch, new_document, open_app_document
from mycad.core.persistence import save_document
from mycad.core.sketch import CircleEntity, LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import (
    SketchBranchChange,
    SketchConstraint,
    SketchConstraintSolveResult,
    SketchGeometryReference,
)
from mycad.core.viewport_protocol import ViewportData, ViewportSketchData
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_constraint_dialog import SketchConstraintDialog

SKETCH_ID = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
LINE_ID = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"


def _sketch() -> Sketch:
    return Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(LINE_ID, (0.0, 0.0), (12.0, 6.0)),),
    )


def test_branch_change_requires_acknowledgement_and_resets_after_edit(qtbot: QtBot) -> None:
    def preview(sketch: Sketch, constraint: SketchConstraint) -> SketchConstraintSolveResult:
        return SketchConstraintSolveResult(
            "success",
            sketch.with_constraint(constraint, sketch.entities),
            0,
            branch_changes=(SketchBranchChange("direction", (LINE_ID,), "方向反转"),),
        )

    dialog = SketchConstraintDialog((_sketch(),), preview)
    qtbot.addWidget(dialog)
    dialog.show()
    captured: list[object] = []

    def capture(*args: object) -> None:
        captured.append(args)

    dialog.commit_requested.connect(capture)
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("length"))
    dialog.preview_button.click()
    assert not dialog.apply_button.isEnabled()
    assert "方向反转" in dialog.detail_label.text()
    assert LINE_ID[:8] in dialog.detail_label.text()
    assert dialog.branch_acknowledgement.isVisible()
    dialog.apply_button.clicked.emit()
    assert not captured
    dialog.branch_acknowledgement.setChecked(True)
    assert dialog.apply_button.isEnabled()
    dialog.value_field.setValue(30.0)
    assert not dialog.apply_button.isEnabled()
    assert not dialog.branch_acknowledgement.isChecked()
    dialog.preview_button.click()
    assert not dialog.apply_button.isEnabled()
    dialog.submission_failed("检查重试门禁")
    assert not dialog.apply_button.isEnabled()
    dialog.branch_acknowledgement.setChecked(True)
    dialog.apply_button.click()
    assert len(captured) == 1


def test_constraint_dialog_previews_then_emits_explicit_commit(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    dialog = SketchConstraintDialog((_sketch(),), services.kernel.preview_sketch_constraint)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("length"))
    dialog.value_field.setValue(24.0)

    dialog.preview_button.click()

    assert dialog.status_label.text().startswith("求解成功")
    assert dialog.apply_button.isEnabled()
    assert "线段" in dialog.unit_label.text() or dialog.unit_label.text() == "mm"
    captured: list[tuple[Sketch, SketchConstraint, SketchConstraintSolveResult]] = []

    def capture(sketch: object, constraint: object, result: object) -> None:
        assert isinstance(sketch, Sketch)
        assert isinstance(constraint, SketchConstraint)
        assert isinstance(result, SketchConstraintSolveResult)
        captured.append((sketch, constraint, result))

    dialog.commit_requested.connect(capture)
    dialog.apply_button.click()
    assert captured[0][0] == _sketch()
    assert captured[0][1].kind == "length"
    assert captured[0][2].status == "success"
    assert not dialog.apply_button.isEnabled()


def test_reference_dimension_measures_geometry_without_moving_it(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    sketch = _sketch()
    dialog = SketchConstraintDialog((sketch,), services.kernel.preview_sketch_constraint)
    qtbot.addWidget(dialog)
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("length"))
    dialog.driving_check.setChecked(False)

    dialog.preview_button.click()

    assert dialog.status_label.text().startswith("求解成功")
    assert dialog.value_field.isReadOnly()
    assert dialog.value_field.value() == pytest.approx((180.0**0.5), abs=1e-6)
    assert dialog.apply_button.isEnabled()


@pytest.mark.parametrize("kind", ["radius", "diameter", "arc_length"])
@pytest.mark.parametrize("driving", [False, True])
def test_curved_polyline_segment_dimension_from_constraint_dialog(
    qtbot: QtBot, kind: str, driving: bool
) -> None:
    services = build_app(discoverers=())
    polyline = PolylineEntity(LINE_ID, ((0, 0), (10, 0), (10, 10)), bulges=(0, 0.5))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (polyline,))
    dialog = SketchConstraintDialog((sketch,), services.kernel.preview_sketch_constraint)
    qtbot.addWidget(dialog)
    dialog.show()
    kind_index = dialog.kind_combo.findData(kind)
    assert kind_index >= 0
    dialog.kind_combo.setCurrentIndex(kind_index)
    assert dialog.first_reference.currentData() == "segment"
    dialog.first_index.setValue(1)
    dialog.driving_check.setChecked(driving)
    if driving:
        dialog.value_field.setValue({"radius": 7.5, "diameter": 15.0, "arc_length": 12.0}[kind])
    dialog.preview_button.click()
    if dialog.branch_acknowledgement.isVisible():
        dialog.branch_acknowledgement.setChecked(True)
    assert dialog.status_label.text().startswith("求解成功"), dialog.status_label.text()
    assert dialog.apply_button.isEnabled()
    assert dialog.value_field.value() > 0


def test_existing_arc_length_dimension_is_available_for_editing(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    polyline = PolylineEntity(LINE_ID, ((0, 0), (10, 0), (10, 10)), bulges=(0, 0.5))
    dimension = SketchConstraint(
        "22222222-2222-4222-8222-222222222222",
        "arc_length",
        (SketchGeometryReference(LINE_ID, "segment", 1),),
        10,
        "mm",
        False,
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (polyline,), (dimension,))
    dialog = SketchConstraintDialog((sketch,), services.kernel.preview_sketch_constraint)
    qtbot.addWidget(dialog)
    assert dialog.dimension_combo.findData(dimension.constraint_id) >= 0
    dialog.dimension_combo.setCurrentIndex(dialog.dimension_combo.findData(dimension.constraint_id))
    assert dialog.kind_combo.currentData() == "arc_length"
    assert dialog.first_reference.currentData() == "segment"
    assert dialog.first_index.value() == 1


def test_dimension_precision_and_scale_are_part_of_the_previewed_constraint(
    qtbot: QtBot,
) -> None:
    services = build_app(discoverers=())
    dialog = SketchConstraintDialog((_sketch(),), services.kernel.preview_sketch_constraint)
    qtbot.addWidget(dialog)
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("length"))
    dialog.precision_field.setValue(4)
    dialog.scale_field.setValue(2.5)
    captured: list[SketchConstraint] = []

    def capture(_sketch: object, constraint: object, _result: object) -> None:
        assert isinstance(constraint, SketchConstraint)
        captured.append(constraint)

    dialog.commit_requested.connect(capture)

    dialog.preview_button.click()

    assert dialog.apply_button.isEnabled()
    dialog.apply_button.click()
    assert captured
    constraint = captured[0]
    assert constraint.precision == 4
    assert constraint.scale == pytest.approx(2.5)


def test_main_window_constraint_action_commits_through_bus(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute("sketch.create", _sketch().to_mapping(), confirmed_by="local")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()

    def accept_constraint() -> None:
        dialog = window.active_sketch_constraint_dialog()
        assert dialog is not None
        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("length"))
        dialog.value_field.setValue(24.0)
        dialog.preview_button.click()
        qtbot.waitUntil(dialog.apply_button.isEnabled, timeout=5000)
        dialog.apply_button.click()

    stalled_dialog_status: list[str] = []

    def close_stalled_dialog() -> None:
        dialog = window.active_sketch_constraint_dialog()
        if dialog is not None:
            stalled_dialog_status.append(dialog.status_label.text())
            dialog.reject()

    QTimer.singleShot(100, accept_constraint)
    QTimer.singleShot(3000, close_stalled_dialog)
    window.act_sketch_constraints.trigger()

    assert stalled_dialog_status == [], f"constraint submission stalled: {stalled_dialog_status}"

    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=5000)
    assert len(loaded.document.commands) == 2
    assert loaded.document.commands[-1].id == "sketch.constraint.add"
    assert services.kernel.sketches[0].constraints[0].kind == "length"


def test_main_window_constrains_straight_segment_of_curved_polyline(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    path = PolylineEntity(LINE_ID, ((0, 0), (3, 2), (9, 3)), bulges=(0.5, 0))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (path,))
    commit_new_sketch(services, loaded, sketch, session_identity=1)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()

    def accept_constraint() -> None:
        dialog = window.active_sketch_constraint_dialog()
        assert dialog is not None
        try:
            dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("horizontal"))
            dialog.first_reference.setCurrentIndex(dialog.first_reference.findData("segment"))
            dialog.first_index.setValue(1)
            dialog.preview_button.click()
            qtbot.waitUntil(dialog.apply_button.isEnabled, timeout=10000)
            dialog.apply_button.click()
        except BaseException:
            dialog.reject()
            raise

    QTimer.singleShot(0, accept_constraint)
    window.act_sketch_constraints.trigger()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=10000)
    solved = services.kernel.sketches[0].entities[0]
    assert isinstance(solved, PolylineEntity) and solved.bulges == path.bulges
    assert solved.points_mm[1][1] == pytest.approx(solved.points_mm[2][1])
    loaded.bus.undo()
    assert services.kernel.sketches[0] == sketch


def test_main_window_adds_and_edits_polyline_arc_length(qtbot: QtBot, tmp_path: Path) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    path = PolylineEntity(LINE_ID, ((0, 0), (10, 0), (10, 10)), bulges=(0, 0.5))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (path,))
    commit_new_sketch(services, loaded, sketch, session_identity=1)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()

    def apply_dimension(*, edit: bool) -> None:
        dialog = window.active_sketch_constraint_dialog()
        assert dialog is not None
        try:
            if edit:
                dimension = services.kernel.sketches[0].constraints[0]
                dialog.dimension_combo.setCurrentIndex(
                    dialog.dimension_combo.findData(dimension.constraint_id)
                )
                assert dialog.kind_combo.currentData() == "arc_length"
                assert dialog.first_reference.currentData() == "segment"
                assert dialog.first_index.value() == 1
            else:
                dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("arc_length"))
                dialog.first_index.setValue(1)
            dialog.value_field.setValue(13 if edit else 12)
            dialog.preview_button.click()
            qtbot.waitUntil(
                lambda: (
                    dialog.apply_button.isEnabled() or dialog.branch_acknowledgement.isVisible()
                ),
                timeout=10000,
            )
            if dialog.branch_acknowledgement.isVisible():
                dialog.branch_acknowledgement.setChecked(True)
            assert dialog.apply_button.isEnabled(), dialog.status_label.text()
            dialog.apply_button.click()
        except BaseException:
            dialog.reject()
            raise

    unit = window.execution_unit
    assert unit is not None
    for edit in (False, True):
        QTimer.singleShot(0, partial(apply_dimension, edit=edit))
        window.act_sketch_constraints.trigger()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == 3
    assert services.kernel.sketches[0].constraints[0].value == pytest.approx(13)
    after = services.kernel.sketches
    save_path = tmp_path / "dialog-arc-length.my2d"
    save_document(loaded.document, save_path)
    reopened = open_app_document(services, save_path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches[0].constraints[0].value == pytest.approx(12)


def test_async_constraint_preview_ignores_results_after_input_changes(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    dialog = SketchConstraintDialog(
        (_sketch(),), services.kernel.preview_sketch_constraint, asynchronous_preview=True
    )
    qtbot.addWidget(dialog)
    requests: list[tuple[Sketch, SketchConstraint, int]] = []

    def record_request(sketch: Sketch, constraint: SketchConstraint, token: int) -> None:
        requests.append((sketch, constraint, token))

    dialog.preview_requested.connect(record_request)
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("length"))
    dialog.preview_button.click()
    assert not dialog.apply_button.isEnabled()
    sketch, constraint, token = requests[-1]
    result = services.kernel.preview_sketch_constraint(sketch, constraint)
    dialog.value_field.setValue(15.0)
    assert not dialog.complete_preview(token, sketch, constraint, result)
    assert not dialog.apply_button.isEnabled()
    dialog.preview_button.click()
    sketch, constraint, token = requests[-1]
    result = services.kernel.preview_sketch_constraint(sketch, constraint)
    assert dialog.complete_preview(token, sketch, constraint, result)
    assert dialog.apply_button.isEnabled()


def test_constraint_preview_blocks_confirmation_when_downstream_rebuild_fails(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (
            CircleEntity(LINE_ID, (0.0, 0.0), 5.0),
            CircleEntity("2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c", (0.0, 0.0), 2.0),
        ),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": SKETCH_ID}, "distance": 10.0},
        confirmed_by="local",
    )
    commands = loaded.document.commands
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    observed: list[str] = []

    def try_constraint() -> None:
        dialog = window.active_sketch_constraint_dialog()
        assert dialog is not None
        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("radius"))
        dialog.value_field.setValue(2.0)
        dialog.preview_button.click()
        qtbot.waitUntil(lambda: "重建失败" in dialog.status_label.text(), timeout=5000)
        observed.append(dialog.status_label.text())
        assert not dialog.apply_button.isEnabled()
        assert loaded.document.commands == commands
        assert services.kernel.sketches == (sketch,)
        dialog.reject()

    QTimer.singleShot(100, try_constraint)

    def close_stalled() -> None:
        dialog = window.active_sketch_constraint_dialog()
        if dialog is not None:
            dialog.reject()

    QTimer.singleShot(6000, close_stalled)
    window.act_sketch_constraints.trigger()
    assert observed


@pytest.mark.parametrize(
    ("existing_dimension", "branch_warning"), [(False, False), (True, False), (True, True)]
)
def test_constraint_preview_shows_solved_sketch_and_solid_before_confirmation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, existing_dimension: bool, branch_warning: bool
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    dimension = SketchConstraint(
        "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c",
        "radius",
        (SketchGeometryReference(LINE_ID, "geometry"),),
        5.0,
        "mm",
    )
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (CircleEntity(LINE_ID, (0.0, 0.0), 5.0),),
        (dimension,) if existing_dimension else (),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": SKETCH_ID}, "distance": 10.0},
        confirmed_by="local",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    if branch_warning:
        original_solve = services.kernel.preview_sketch_constraint_update

        def flagged_solve(base: Sketch, candidate: SketchConstraint) -> SketchConstraintSolveResult:
            return replace(
                original_solve(base, candidate),
                branch_changes=(SketchBranchChange("nesting", (LINE_ID,), "内外关系改变"),),
            )

        monkeypatch.setattr(services.kernel, "preview_sketch_constraint_update", flagged_solve)
    viewport = window.viewport
    assert viewport is not None
    committed_state = viewport.displayed_snapshot_id()
    original_show = viewport.show_candidate_preview
    previews: list[tuple[ViewportData, tuple[ViewportSketchData, ...] | None]] = []

    def capture_preview(
        snapshot: ViewportData,
        *,
        preserve_view: bool = False,
        sketches: tuple[ViewportSketchData, ...] | None = None,
    ) -> None:
        previews.append((snapshot, sketches))
        original_show(snapshot, preserve_view=preserve_view, sketches=sketches)

    monkeypatch.setattr(viewport, "show_candidate_preview", capture_preview)

    def preview_and_confirm() -> None:
        dialog = window.active_sketch_constraint_dialog()
        assert dialog is not None
        if existing_dimension:
            dialog.dimension_combo.setCurrentIndex(
                dialog.dimension_combo.findData(dimension.constraint_id)
            )
        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("radius"))
        dialog.value_field.setValue(7.0)
        dialog.preview_button.click()
        qtbot.waitUntil(lambda: bool(previews), timeout=5000)
        if branch_warning:
            assert not dialog.apply_button.isEnabled()
            dialog.branch_acknowledgement.setChecked(True)
        assert dialog.apply_button.isEnabled()
        snapshot, sketch_preview = previews[-1]
        assert max(point[0] for point in snapshot.mesh.vertices) == pytest.approx(7.0, abs=0.02)
        assert sketch_preview is not None
        assert sketch_preview[0].curves[0].layer.color_rgb == (
            (230, 126, 34) if branch_warning else sketch.layers.layers[0].color_rgb
        )
        assert max(point[0] for point in sketch_preview[0].curves[0].points) == pytest.approx(7.0)
        assert services.kernel.mass_properties().volume == pytest.approx(250.0 * math.pi)
        assert len(loaded.document.commands) == 2
        dialog.value_field.setValue(8.0)
        assert viewport.displayed_snapshot_id() == committed_state
        assert not dialog.apply_button.isEnabled()
        dialog.preview_button.click()
        qtbot.waitUntil(lambda: len(previews) == 2, timeout=5000)
        if branch_warning:
            assert not dialog.apply_button.isEnabled()
            dialog.branch_acknowledgement.setChecked(True)
        assert dialog.apply_button.isEnabled()
        dialog.apply_button.click()

    def close_stalled() -> None:
        dialog = window.active_sketch_constraint_dialog()
        if dialog is not None:
            dialog.reject()

    QTimer.singleShot(100, preview_and_confirm)
    QTimer.singleShot(8000, close_stalled)
    window.act_sketch_constraints.trigger()
    assert len(loaded.document.commands) == 3
    assert loaded.document.commands[-1].id == (
        "sketch.constraint.update" if existing_dimension else "sketch.constraint.add"
    )
    assert services.kernel.mass_properties().volume == pytest.approx(640.0 * math.pi)


def test_existing_dimension_selection_preserves_identity_and_previews_revision(
    qtbot: QtBot,
) -> None:
    services = build_app(discoverers=())
    dimension = SketchConstraint(
        "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c",
        "radius",
        (SketchGeometryReference(LINE_ID, "geometry"),),
        5.0,
        "mm",
        precision=3,
    )
    sketch = Sketch(
        SKETCH_ID, WorkPlaneFrame.xy(), (CircleEntity(LINE_ID, (0.0, 0.0), 5.0),), (dimension,)
    )
    dialog = SketchConstraintDialog(
        (sketch,),
        services.kernel.preview_sketch_constraint,
        preview_update=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(dialog)
    dialog.dimension_combo.setCurrentIndex(dialog.dimension_combo.findData(dimension.constraint_id))
    assert dialog.value_field.value() == 5.0
    assert dialog.precision_field.value() == 3
    assert not dialog.kind_combo.isEnabled()
    assert not dialog.first_entity.isEnabled()
    assert dialog.apply_button.text() == "确认修改"
    dialog.value_field.setValue(7.0)
    captured: list[SketchConstraint] = []

    def record(
        _sketch: Sketch, constraint: SketchConstraint, _result: SketchConstraintSolveResult
    ) -> None:
        captured.append(constraint)

    dialog.commit_requested.connect(record)
    dialog.preview_button.click()
    assert dialog.apply_button.isEnabled(), dialog.status_label.text()
    dialog.apply_button.click()
    assert captured == [replace(dimension, value=7.0)]
    assert sketch.constraints == (dimension,)


def test_conflict_details_name_the_pending_relation_and_its_geometry(qtbot: QtBot) -> None:
    horizontal = SketchConstraint(
        "44444444-4444-4444-8444-444444444444",
        "horizontal",
        (SketchGeometryReference(LINE_ID, "geometry"),),
    )
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(LINE_ID, (0.0, 0.0), (12.0, 0.0)),),
        (horizontal,),
    )

    def preview(base: Sketch, pending: SketchConstraint) -> SketchConstraintSolveResult:
        return SketchConstraintSolveResult(
            "failed",
            None,
            None,
            conflicting_constraint_ids=(horizontal.constraint_id, pending.constraint_id),
        )

    dialog = SketchConstraintDialog((sketch,), preview)
    qtbot.addWidget(dialog)
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("vertical"))
    dialog.preview_button.click()
    detail = dialog.detail_label.text()
    assert "水平" in detail and "竖直" in detail
    assert "直线" in detail and LINE_ID[:8] in detail
    assert "整个图元" in detail
    assert not dialog.apply_button.isEnabled()


def test_real_conflict_highlights_original_geometry_then_corrected_input_can_commit(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    horizontal = SketchConstraint(
        "44444444-4444-4444-8444-444444444444",
        "horizontal",
        (SketchGeometryReference(LINE_ID, "geometry"),),
        source="inferred",
    )
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (LineEntity(LINE_ID, (0.0, 0.0), (12.0, 0.0)),),
        (horizontal,),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "test")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    viewport = window.viewport
    assert viewport is not None
    previews: list[tuple[ViewportSketchData, ...]] = []
    original_show = viewport.show_candidate_preview

    def capture(
        snapshot: ViewportData,
        *,
        preserve_view: bool = False,
        sketches: tuple[ViewportSketchData, ...] | None = None,
    ) -> None:
        if sketches is not None:
            previews.append(sketches)
        original_show(snapshot, preserve_view=preserve_view, sketches=sketches)

    monkeypatch.setattr(viewport, "show_candidate_preview", capture)

    def exercise() -> None:
        dialog = window.active_sketch_constraint_dialog()
        assert dialog is not None
        try:
            dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("vertical"))
            dialog.preview_button.click()
            qtbot.waitUntil(lambda: bool(dialog.detail_label.text()), timeout=10000)
            assert not dialog.apply_button.isEnabled()
            assert previews, "a conflict must locate its referenced original curves"
            assert previews[-1][0].curves[0].layer.color_rgb == (200, 45, 45)
            assert (
                previews[-1][0].curves[0].points
                == services.kernel.sketch_display_data()[0].curves[0].points
            )
            assert len(loaded.document.commands) == 1 and services.kernel.sketches == (sketch,)
            dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("length"))
            dialog.value_field.setValue(20)
            assert not dialog.apply_button.isEnabled()
            dialog.preview_button.click()
            qtbot.waitUntil(dialog.apply_button.isEnabled, timeout=10000)
            assert previews[-1][0].curves[0].layer.color_rgb == sketch.layers.layers[0].color_rgb
            assert not dialog.detail_label.text()
            dialog.apply_button.click()
        except BaseException:
            dialog.reject()
            raise

    QTimer.singleShot(0, exercise)
    window.act_sketch_constraints.trigger()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=10000)
    assert services.kernel.sketches[0].constraints[0] == horizontal
    line = services.kernel.sketches[0].entities[0]
    assert isinstance(line, LineEntity)
    assert math.dist(line.start_mm, line.end_mm) == pytest.approx(20)


def test_locked_geometry_is_labelled_and_only_reference_measurement_can_commit(
    qtbot: QtBot,
) -> None:
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    services = build_app(discoverers=())
    circle = CircleEntity(LINE_ID, (0.0, 0.0), 5.0, layer_name="locked")
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (circle,),
        layers=SketchLayerTable().add(SketchLayer("locked", locked=True)),
    )
    dialog = SketchConstraintDialog((sketch,), services.kernel.preview_sketch_constraint)
    qtbot.addWidget(dialog)
    assert "锁定" in dialog.first_entity.currentText()
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("radius"))
    dialog.value_field.setValue(7.0)
    dialog.preview_button.click()
    assert "锁定" in dialog.status_label.text()
    assert not dialog.apply_button.isEnabled()
    dialog.driving_check.setChecked(False)
    dialog.preview_button.click()
    assert dialog.apply_button.isEnabled()
    assert sketch.entities == (circle,)
