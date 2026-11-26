# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Identity-bearing curves coexist with interactive dimension solving."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.geometric_tolerance_topology import prepare_curve_identity_upgrade
from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("entry", ["command", "menu"])
def test_upgrade_selected_legacy_curve_from_drawing_ui(qtbot: QtBot, entry: str) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    assert editor.canvas.selected_entity_ids == {curve.entity_id}
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    if entry == "command":
        editor.drawing_command_bar.input.setText("CURVEIDUPGRADE")
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    else:
        menus = [
            menu
            for action in editor.dimension_toolbar.actions()
            if isinstance((menu := action.menu()), QMenu)
        ]
        actions = [action for menu in menus for action in menu.actions()]
        next(action for action in actions if action.text() == "升级曲线点身份").trigger()
    upgraded = services.kernel.sketches[0].entities[0]
    assert isinstance(upgraded, PolylineEntity) and upgraded.point_ids
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.sketches == (sketch,))


@pytest.mark.parametrize("additive", [False, True])
def test_curve_upgrade_after_switching_selection_from_datum(qtbot: QtBot, additive: bool) -> None:
    from collections.abc import Callable
    from typing import cast

    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (20, 15))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    sync = cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])
    sync(window)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    assert tools.selected_id == datum.datum_id
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier if additive else Qt.KeyboardModifier.NoModifier,
        canvas.local_to_screen((5, 0)),
    )
    assert canvas.selected_entity_ids == {curve.entity_id}
    tools.upgrade_curve_identities()
    upgraded = services.kernel.sketches[0].entities[0]
    assert isinstance(upgraded, PolylineEntity)
    if additive:
        assert tools.selected_id == datum.datum_id
        assert not upgraded.point_ids and "仅选择" in editor.status_label.text()
    else:
        assert tools.selected_id is None and upgraded.point_ids
    assert services.kernel.drawing_datum_identifiers == (datum,)


@pytest.mark.parametrize("other", ["annotation", "constraint", "raster", "text"])
def test_curve_upgrade_rejects_mixed_selection(qtbot: QtBot, other: str) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.selected_entity_ids = {curve.entity_id}
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    identity = uuid4().hex
    if other == "annotation":
        tools.selected_ids = {identity}
        tools.selected_id = identity
    elif other == "constraint":
        canvas.selected_constraint_ids = {identity}
    elif other == "raster":
        canvas.selected_raster_ids = {identity}
    else:
        assert canvas.text_tools is not None
        canvas.text_tools.selected_ids = {identity}
    count = loaded.document.command_count
    tools.upgrade_curve_identities()
    assert services.kernel.sketches == (sketch,)
    assert loaded.document.command_count == count
    assert "仅选择" in editor.status_label.text()


def test_dimension_preview_and_commit_preserves_unrelated_curve_identities(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    curve = PolylineEntity(uuid4().hex, ((20, 0), (22, 0), (22, 2)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, curve))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    record = prepare_curve_identity_upgrade(sketch, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["horizontal"].click()
    for point in ((5, 0), (5, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    editor.dimensions.value_editor.setValue(12)
    constraint, original = editor.dimensions.candidate, editor.dimensions.original
    assert constraint is not None and original is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, constraint) is not None, timeout=15000
    )
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(
        lambda: not unit.is_busy and loaded.document.commands[-1].id == "sketch.constraint.add",
        timeout=15000,
    )
    assert loaded.document.commands[-1].version == 11
    solved_curve = services.kernel.sketches[0].entities[1]
    assert isinstance(solved_curve, PolylineEntity)
    assert solved_curve.point_ids == record.point_ids


@pytest.mark.parametrize("curve_tangent", [False, True])
def test_linked_dimension_preview_and_commit_preserves_curve_ids(
    qtbot: QtBot, curve_tangent: bool
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    curve = PolylineEntity(
        uuid4().hex,
        ((-10, 0), (10, 0), (10, -5)) if curve_tangent else ((20, 0), (22, 0), (22, 2)),
    )
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,) if curve_tangent else (line, curve))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, curve.entity_id, 0)
        if curve_tangent
        else CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    current = next(item for item in services.kernel.sketches if item.sketch_id == first.sketch_id)
    record = prepare_curve_identity_upgrade(current, (curve.entity_id,))[0]
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "records": [record.to_mapping()],
        },
        "local",
    )
    editor.set_context_sketches(services.kernel.sketches)
    source = next(item for item in services.kernel.sketches if item.sketch_id == second.sketch_id)
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["radius"].click()
    for point in ((0, 4), (8, 8)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    editor.dimensions.value_editor.setValue(3)
    constraint = editor.dimensions.candidate
    assert constraint is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(source, constraint) is not None, timeout=15000
    )
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(
        lambda: not unit.is_busy and loaded.document.commands[-1].id == "drawing.sketch.revise",
        timeout=15000,
    )
    assert loaded.document.commands[-1].version == 64
    solved = next(
        item for item in services.kernel.sketches if item.sketch_id == first.sketch_id
    ).entities[0 if curve_tangent else 1]
    assert isinstance(solved, PolylineEntity) and solved.point_ids == record.point_ids
    if curve_tangent:
        assert solved.points_mm != curve.points_mm


def test_exact_reorder_with_ids_and_datum_uses_proven_map(qtbot: QtBot, tmp_path: Path) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(curve.entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_entity_ids = {curve.entity_id}
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.upgrade_curve_identities()
    current = services.kernel.sketches[0]
    identified_curve = current.entities[0]
    assert isinstance(identified_curve, PolylineEntity) and identified_curve.point_ids
    assert services.kernel.drawing_datum_identifiers == (datum,)
    reversed_curve = replace(
        curve,
        points_mm=tuple(reversed(curve.points_mm)),
        point_ids=tuple(reversed(identified_curve.point_ids)),
    )
    updated = replace(current, entities=(reversed_curve,))
    state = updated.to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 64
    assert services.kernel.sketches == (updated,)
    attachment = services.kernel.drawing_datum_identifiers[0].attachment
    assert attachment is not None and attachment.reference.index == 2
    assert services.kernel.drawing_datum_identifiers[0].target_mm == (0, 0)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.sketches == (current,), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.sketches == (sketch,), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.sketches == (current,), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.sketches == (updated,), timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    from mycad.core.persistence import save_document

    path = tmp_path / "curve-upgrade-reorder.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    restored = reopened.kernel.drawing_datum_identifiers[0]
    assert restored.attachment is not None and restored.attachment.reference.index == 2
    assert restored.target_mm == (0, 0)


def test_array_reorder_entry_preserves_member_point_ids_and_datum(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    target = PolylineEntity(uuid4().hex, ((0, 20), (10, 20), (10, 30)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    a, b = (
        ArrayEntityRef(sketch.sketch_id, source.entity_id),
        ArrayEntityRef(sketch.sketch_id, target.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (a,), (ArrayMember(a, b, 1, 0),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(array,))
    records = prepare_curve_identity_upgrade(sketch, (source.entity_id, target.entity_id))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 24),
        (0, 20),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(target.entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]
    reversed_source = replace(
        source,
        points_mm=tuple(reversed(source.points_mm)),
        point_ids=tuple(reversed(records[0].point_ids)),
    )
    frozen = replace(current, entities=(reversed_source, current.entities[1])).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 64
    member = services.kernel.sketches[0].entities[1]
    assert isinstance(member, PolylineEntity) and member.point_ids == tuple(
        reversed(records[1].point_ids)
    )
    attachment = services.kernel.drawing_datum_identifiers[0].attachment
    assert attachment is not None and attachment.reference.index == 2


def test_replacement_source_reorder_entry_selects_version_65(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    replacement = replace(
        source, entity_id=uuid4().hex, points_mm=tuple((x + 30, y) for x, y in source.points_mm)
    )
    target = replace(
        source, entity_id=uuid4().hex, points_mm=tuple((x, y + 20) for x, y in source.points_mm)
    )
    sketches = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,)) for item in (source, replacement, target)
    )
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    refs = tuple(
        ArrayEntityRef(sketch.sketch_id, sketch.entities[0].entity_id) for sketch in sketches
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketches[0].frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    for sketch in sketches:
        current = next(
            item for item in services.kernel.sketches if item.sketch_id == sketch.sketch_id
        )
        records = prepare_curve_identity_upgrade(current, (sketch.entities[0].entity_id,))
        loaded.bus.execute(
            "drawing.curve_identity.upgrade",
            {
                "sketch_id": current.sketch_id,
                "base_state_sha256": current.local_state_digest(),
                "records": [record.to_mapping() for record in records],
            },
            "local",
        )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (8, 25),
        (2.5, 20),
        attachment=DatumAttachment(
            sketches[2].sketch_id, SketchGeometryReference(target.entity_id, "segment", 0), 0.25, 4
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = next(
        item for item in services.kernel.sketches if item.sketch_id == sketches[1].sketch_id
    )
    original = current.entities[0]
    assert isinstance(original, PolylineEntity)
    target_before = next(
        item for item in services.kernel.sketches if item.sketch_id == sketches[2].sketch_id
    ).entities[0]
    assert isinstance(target_before, PolylineEntity)
    order = (0, 3, 2, 1)
    changed = replace(
        original,
        points_mm=tuple(original.points_mm[i] for i in order),
        point_ids=tuple(original.point_ids[i] for i in order),
    )
    state = replace(current, entities=(changed,)).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 65
    target_after = next(
        item for item in services.kernel.sketches if item.sketch_id == sketches[2].sketch_id
    ).entities[0]
    assert isinstance(target_after, PolylineEntity)
    assert target_after.point_ids == tuple(target_before.point_ids[i] for i in order)
    attachment = services.kernel.drawing_datum_identifiers[0].attachment
    assert attachment is not None and attachment.reference.index == 3


def test_chained_array_reorder_entry_selects_version_66(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = tuple(
        PolylineEntity(uuid4().hex, ((0, y), (10, y), (10, y + 10))) for y in (0, 20, 40, 60)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    arrays = tuple(
        AssociativeRectArray(
            uuid4().hex, sketch.frame, 2, 1, 20, 0, (a,), (ArrayMember(a, b, 1, 0),)
        )
        for a, b in zip(refs[:-1], refs[1:], strict=True)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=arrays)
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 64),
        (0, 60),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]
    source = replace(
        entities[0],
        points_mm=tuple(reversed(entities[0].points_mm)),
        point_ids=tuple(reversed(records[0].point_ids)),
    )
    frozen = replace(current, entities=(source, *current.entities[1:])).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 66
    for member, record in zip(services.kernel.sketches[0].entities, records, strict=True):
        assert isinstance(member, PolylineEntity)
        assert member.point_ids == tuple(reversed(record.point_ids))
    attachment = services.kernel.drawing_datum_identifiers[0].attachment
    assert attachment is not None and attachment.reference.index == 2


def test_rotated_chain_reorder_entry_selects_version_67(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = [PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    arrays = tuple(
        AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (a,),
            (ArrayMember(a, b, 1, 0, rotation_deg=angle),),
        )
        for a, b, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=arrays)
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    target = entities[-1].points_mm[0]
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 50),
        target,
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]
    old = entities[0]
    source = replace(
        old,
        points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
        point_ids=(records[0].point_ids[0], *reversed(records[0].point_ids[1:])),
    )
    frozen = replace(current, entities=(source, *current.entities[1:])).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 67
    for member, record in zip(services.kernel.sketches[0].entities, records, strict=True):
        assert isinstance(member, PolylineEntity)
        assert member.point_ids == (record.point_ids[0], *reversed(record.point_ids[1:]))
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx(target)


def test_stable_dynamic_base_chain_entry_selects_version_68(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = [PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    arrays = tuple(
        AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (a,),
            (ArrayMember(a, b, 1, 0, rotation_deg=angle),),
            base_point=ArrayBasePoint(
                source=a, reference=SketchGeometryReference(a.entity_id, "vertex", 0)
            )
            if a == refs[1]
            else None,
        )
        for a, b, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=arrays)
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    target = entities[-1].points_mm[0]
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 50),
        target,
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]
    old = entities[0]
    source = replace(
        old,
        points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
        point_ids=(records[0].point_ids[0], *reversed(records[0].point_ids[1:])),
    )
    frozen = replace(current, entities=(source, *current.entities[1:])).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 68
    for member, record in zip(services.kernel.sketches[0].entities, records, strict=True):
        assert isinstance(member, PolylineEntity)
        assert member.point_ids == (record.point_ids[0], *reversed(record.point_ids[1:]))
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx(target)


def test_stable_nonzero_base_chain_entry_selects_version_69(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = [PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    arrays = tuple(
        AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (a,),
            (ArrayMember(a, b, 1, 0, rotation_deg=angle),),
            base_point=ArrayBasePoint(
                source=a, reference=SketchGeometryReference(a.entity_id, "vertex", 2)
            )
            if a == refs[1]
            else None,
        )
        for a, b, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=arrays)
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    target = entities[-1].points_mm[0]
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 50),
        target,
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]
    old = entities[0]
    source = replace(
        old,
        points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
        point_ids=(records[0].point_ids[0], *reversed(records[0].point_ids[1:])),
    )
    frozen = replace(current, entities=(source, *current.entities[1:])).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 69
    for member, record in zip(services.kernel.sketches[0].entities, records, strict=True):
        assert isinstance(member, PolylineEntity)
        assert member.point_ids == (record.point_ids[0], *reversed(record.point_ids[1:]))
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx(target)


def test_rebound_dynamic_base_chain_entry_selects_version_70(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import move_entities, rotate_entities

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = [PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)]
    for angle in (90, 180):
        source = entities[-1]
        rotated = rotate_entities((source,), (source.entity_id,), source.points_mm[0], angle)[0]
        moved = move_entities((rotated,), (source.entity_id,), (0, 20))[0]
        assert isinstance(moved, PolylineEntity)
        entities.append(replace(moved, entity_id=uuid4().hex))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), tuple(entities))
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    arrays = tuple(
        AssociativeRectArray(
            uuid4().hex,
            sketch.frame,
            2,
            1,
            20,
            0,
            (a,),
            (ArrayMember(a, b, 1, 0, rotation_deg=angle),),
            base_point=ArrayBasePoint(
                source=a, reference=SketchGeometryReference(a.entity_id, "vertex", 1)
            )
            if a == refs[1]
            else None,
        )
        for a, b, angle in zip(refs[:-1], refs[1:], (90, 180), strict=True)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=arrays)
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    target = entities[-1].points_mm[0]
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 50),
        target,
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[-1].entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]
    old = entities[0]
    source = replace(
        old,
        points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
        point_ids=(records[0].point_ids[0], *reversed(records[0].point_ids[1:])),
    )
    frozen = replace(current, entities=(source, *current.entities[1:])).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 70
    for member, record in zip(services.kernel.sketches[0].entities, records, strict=True):
        assert isinstance(member, PolylineEntity)
        assert member.point_ids == (record.point_ids[0], *reversed(record.point_ids[1:]))
    assert services.kernel.drawing_datum_identifiers[0].target_mm == pytest.approx(target)

    rebound = next(
        item for item in services.kernel.associative_arrays if item.base_point is not None
    )
    assert rebound.base_point is not None and rebound.base_point.reference is not None
    assert rebound.base_point.reference.index == 3


def test_unchanged_replacement_chain_entry_selects_version_71(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = tuple(
        PolylineEntity(
            uuid4().hex, ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)), closed=True
        )
        for x, y in ((0, 0), (30, 0), (0, 20), (0, 40))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
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
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(b, a))
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 44),
        (0, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]
    source = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(records[0].point_ids[0], *reversed(records[0].point_ids[1:])),
    )
    frozen = replace(current, entities=(source, *current.entities[1:])).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 71
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.sketches[0].entities[1:] == current.entities[1:]


def test_reordered_replacement_chain_entry_selects_version_72(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = tuple(
        PolylineEntity(
            uuid4().hex, ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)), closed=True
        )
        for x, y in ((0, 0), (30, 0), (0, 20), (0, 40))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
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
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(b, a))
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 44),
        (0, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(records[1].point_ids[0], *reversed(records[1].point_ids[1:])),
    )
    frozen = replace(
        current, entities=(current.entities[0], source, *current.entities[2:])
    ).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 72
    assert services.kernel.drawing_datum_identifiers == (datum,)
    for member, record in zip(services.kernel.sketches[0].entities[2:], records[2:], strict=True):
        assert isinstance(member, PolylineEntity)
        assert member.point_ids == (record.point_ids[0], *reversed(record.point_ids[1:]))


def test_extra_output_chain_entry_selects_version_73(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = tuple(
        PolylineEntity(
            uuid4().hex, ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)), closed=True
        )
        for x, y in ((0, 0), (0, 20), (30, 0), (0, 20), (0, 40))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
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
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(b, a))
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (12, 44),
        (10, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "vertex", 1)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]
    old = entities[2]
    changed = replace(
        old,
        points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
        point_ids=(records[2].point_ids[0], *reversed(records[2].point_ids[1:])),
    )
    frozen = replace(
        current, entities=(*current.entities[:2], changed, *current.entities[3:])
    ).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 73
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)


def test_simultaneous_replacement_chain_entry_selects_version_74(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = tuple(
        PolylineEntity(
            uuid4().hex, ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)), closed=True
        )
        for x, y in ((0, 0), (30, 0), (0, 20), (0, 40))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
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
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(b, a))
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 44),
        (0, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(records[1].point_ids[0], *reversed(records[1].point_ids[1:])),
    )
    anchor = replace(
        entities[0],
        points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:])),
        point_ids=(records[0].point_ids[0], *reversed(records[0].point_ids[1:])),
    )
    frozen = replace(current, entities=(anchor, source, *current.entities[2:])).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 74
    assert services.kernel.drawing_datum_identifiers == (datum,)
    for member, record in zip(services.kernel.sketches[0].entities[2:], records[2:], strict=True):
        assert isinstance(member, PolylineEntity)
        assert member.point_ids == (record.point_ids[0], *reversed(record.point_ids[1:]))


def test_generated_replacement_and_anchor_entry_selects_version_75(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = tuple(
        PolylineEntity(
            uuid4().hex, ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)), closed=True
        )
        for x, y in ((20, 0), (30, 0), (0, 0), (0, 20), (0, 40))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    first = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 10, (refs[0],), (ArrayMember(refs[0], refs[1], 0, 1),)
    )
    second = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[2],),
        (ArrayMember(refs[2], refs[3], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    third = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[3],), (ArrayMember(refs[3], refs[4], 1, 0),)
    )
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=0, associative_arrays=(third, second, first)
    )
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (12, 44),
        (10, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "vertex", 1)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]

    def reordered(index: int) -> PolylineEntity:
        old, ids = entities[index], records[index].point_ids
        return replace(
            old,
            points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
            point_ids=(ids[0], *reversed(ids[1:])),
        )

    frozen = replace(
        current, entities=(reordered(0), current.entities[1], reordered(2), *current.entities[3:])
    ).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 75
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)


def test_generated_extra_source_and_anchor_entry_selects_version_75(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = tuple(
        PolylineEntity(
            uuid4().hex, ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)), closed=True
        )
        for x, y in ((20, 0), (30, 0), (0, 0), (0, 20), (0, 40), (0, 20))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    first = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 10, (refs[0],), (ArrayMember(refs[0], refs[1], 0, 1),)
    )
    second = AssociativeRectArray(
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
    third = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[3],), (ArrayMember(refs[3], refs[4], 1, 0),)
    )
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=0, associative_arrays=(third, second, first)
    )
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (12, 44),
        (10, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[4].entity_id, "vertex", 1)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]

    def reordered(index: int) -> PolylineEntity:
        old, ids = entities[index], records[index].point_ids
        return replace(
            old,
            points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
            point_ids=(ids[0], *reversed(ids[1:])),
        )

    frozen = replace(
        current, entities=(reordered(0), current.entities[1], reordered(2), *current.entities[3:])
    ).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 75
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)


def test_internal_extra_source_entry_selects_version_75(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = tuple(
        PolylineEntity(
            uuid4().hex, ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)), closed=True
        )
        for x, y in ((20, 0), (30, 0), (30, 0), (30, 20))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    a = AssociativeRectArray(
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
    b = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[2],), (ArrayMember(refs[2], refs[3], 1, 0),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(b, a))
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (42, 24),
        (40, 20),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "vertex", 1)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]
    old = entities[0]
    changed = replace(
        old,
        points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
        point_ids=(records[0].point_ids[0], *reversed(records[0].point_ids[1:])),
    )
    frozen = replace(current, entities=(changed, *current.entities[1:])).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 75
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)


def test_replacement_with_extra_chain_entry_selects_version_76(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = tuple(
        PolylineEntity(
            uuid4().hex, ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)), closed=True
        )
        for x, y in ((0, 0), (30, 0), (0, 20), (0, 40), (60, 0), (0, 20))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
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
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[2],), (ArrayMember(refs[2], refs[3], 1, 0),)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=(b, a))
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 44),
        (0, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[3].entity_id, "vertex", 0)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]
    source = replace(
        entities[1],
        points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:])),
        point_ids=(records[1].point_ids[0], *reversed(records[1].point_ids[1:])),
    )
    frozen = replace(
        current, entities=(current.entities[0], source, *current.entities[2:])
    ).to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 76
    assert services.kernel.drawing_datum_identifiers == (datum,)
    for member, record in zip(services.kernel.sketches[0].entities[2:4], records[2:4], strict=True):
        assert isinstance(member, PolylineEntity)
        assert member.point_ids == (record.point_ids[0], *reversed(record.point_ids[1:]))


def test_converging_branches_rebind_generated_dynamic_base_in_editor(qtbot: QtBot) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    positions = ((0, 0), (10, 0), (20, 0), (60, 0), (70, 0), (20, 20), (20, 40))
    entities = tuple(
        PolylineEntity(uuid4().hex, ((x, y), (x + 6, y), (x + 6, y + 6), (x, y + 6)), closed=True)
        for x, y in positions
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
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
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=0, associative_arrays=(join, last, a1, b0, a0)
    )
    records = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in entities))
    loaded.bus.execute(
        "drawing.curve_identity.upgrade",
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "records": [record.to_mapping() for record in records],
        },
        "local",
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (25, 46),
        (26, 40),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(entities[6].entity_id, "vertex", 1)
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    current = services.kernel.sketches[0]

    def reverse(index: int) -> PolylineEntity:
        old, ids = entities[index], records[index].point_ids
        return replace(
            old,
            points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])),
            point_ids=(ids[0], *reversed(ids[1:])),
        )

    revised = replace(
        current,
        entities=tuple(reverse(i) if i in (0, 3) else e for i, e in enumerate(current.entities)),
    )
    frozen = revised.to_state_mapping()
    revisions = [
        {
            "sketch_id": current.sketch_id,
            "base_state_sha256": current.local_state_digest(),
            "entities": frozen["entities"],
            "constraints": frozen["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 75
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 3
    assert updated.target_mm == pytest.approx(datum.target_mm)
    updated_join = next(
        a for a in services.kernel.associative_arrays if a.array_id == join.array_id
    )
    assert updated_join.base_point is not None and updated_join.base_point.reference is not None
    assert updated_join.base_point.reference.index == 3


@pytest.mark.parametrize("with_datum", [True, False])
@pytest.mark.parametrize("reverse", [False, True])
def test_editor_reorders_array_member_with_tangent_annotation(
    qtbot: QtBot, with_datum: bool, reverse: bool
) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entities = tuple(
        PolylineEntity(uuid4().hex, ((0, y), (10, y), (10, y + 10), (0, y + 10)), closed=True)
        for y in (0, 20, 40)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    arrays = tuple(
        AssociativeRectArray(
            uuid4().hex, sketch.frame, 2, 1, 20, 0, (a,), (ArrayMember(a, b, 1, 0),)
        )
        for a, b in zip(refs[:-1], refs[1:], strict=True)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0, associative_arrays=arrays)
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
    if with_datum:
        loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    rotated = replace(
        entities[0],
        points_mm=(
            (entities[0].points_mm[0], *reversed(entities[0].points_mm[1:]))
            if reverse
            else (*entities[0].points_mm[1:], entities[0].points_mm[0])
        ),
    )
    revised = replace(sketch, entities=(rotated, *entities[1:]))
    state = revised.to_state_mapping()
    revisions = [
        {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == (78 if reverse else 77)
    assert services.kernel.cross_sketch_tangencies[0].first.segment_index == 3
    assert services.kernel.cross_sketch_tangencies[0].branch == (
        "line_right" if reverse else "line_left"
    )
    if with_datum:
        updated = services.kernel.drawing_datum_identifiers[0]
        assert updated.attachment is not None and updated.attachment.reference.index == 3


@pytest.mark.parametrize("reverse", [False, True])
def test_editor_rebinds_tangency_between_array_source_and_member(
    qtbot: QtBot, tmp_path: Path, reverse: bool
) -> None:
    from dataclasses import replace
    from typing import cast

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    curves = tuple(
        PolylineEntity(
            uuid4().hex, ((x, 0), (x + 10, 0), (x + 10, 10)), closed=True, bulges=(1.0, 0, 0)
        )
        for x in (0, 10)
    )
    sketches = tuple(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,)) for item in curves)
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    source, target = tuple(
        ArrayEntityRef(sketch.sketch_id, curve.entity_id)
        for sketch, curve in zip(sketches, curves, strict=True)
    )
    array = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (source,),
        (ArrayMember(source, target, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(source.sketch_id, source.entity_id, 0),
        CrossSketchRef(target.sketch_id, target.entity_id, 0),
        "external",
        first_endpoint="end",
        second_endpoint="start",
    )
    loaded.bus.execute(
        "drawing.tangency.add",
        {"relation": relation.to_mapping(), "revisions": []},
        "local",
        version=12,
    )
    attachment = DatumAttachment(
        target.sketch_id, SketchGeometryReference(target.entity_id, "segment", 0), 0.25, 3
    )
    point = resolve_attachment_local(attachment, {curves[1].entity_id: curves[1]})
    assert point is not None
    datum = DatumIdentifier(uuid4().hex, "A", (15, -8), point, attachment=attachment)
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    rotated = replace(
        curves[0],
        points_mm=(
            (curves[0].points_mm[0], *reversed(curves[0].points_mm[1:]))
            if reverse
            else (*curves[0].points_mm[1:], curves[0].points_mm[0])
        ),
        bulges=(0, 0, -1 if reverse else 1),
    )
    revised = replace(sketches[0], entities=(rotated,))
    state = revised.to_state_mapping()
    revisions = [
        {
            "sketch_id": source.sketch_id,
            "base_state_sha256": sketches[0].local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
    ]
    partial = replace(
        relation,
        first=replace(relation.first, segment_index=2),
        first_endpoint="start" if reverse else "end",
    )
    mapping = PolylineTopologyMap(curves[0].entity_id, (0, 2, 1) if reverse else (2, 0, 1), 3, True)
    params = {
        "revisions": revisions,
        "remove_tangencies": [relation.relation_id],
        "cross_tangencies": [partial.to_mapping()],
        "polyline_topology_maps": [
            {"sketch_id": source.sketch_id, "mapping": mapping.to_mapping()}
        ],
    }
    from mycad.core.exceptions import ValidationError

    before = services.kernel.sketches
    count = loaded.document.command_count
    with pytest.raises(ValidationError, match="相切"):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=78)
    with pytest.raises(ValidationError, match="相切"):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                **params,
                "cross_tangencies": [
                    replace(partial, first_endpoint="end" if reverse else "start").to_mapping()
                ],
            },
            "local",
            version=79,
        )
    assert loaded.document.command_count == count and services.kernel.sketches == before
    assert services.kernel.cross_sketch_tangencies == (relation,)
    submit = vars(type(window))["_submit_drawing_revisions"]
    submit(window, editor, cast("int", vars(window)["_session_id"]), revisions, False, "测试")
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert loaded.document.commands[-1].id == "drawing.sketch.revise", editor.status_label.text()
    assert loaded.document.commands[-1].version == 79
    expected = replace(
        relation,
        first=replace(relation.first, segment_index=2),
        second=replace(relation.second, segment_index=2),
        first_endpoint="start" if reverse else "end",
        second_endpoint="end" if reverse else "start",
    )
    assert services.kernel.cross_sketch_tangencies == (expected,)
    updated = services.kernel.drawing_datum_identifiers[0]
    assert updated.attachment is not None and updated.attachment.reference.index == 2
    assert updated.target_mm == pytest.approx(point)
    loaded.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.redo_operation()
    from mycad.core.persistence import save_document

    path = tmp_path / "source-member-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.cross_sketch_tangencies == (expected,)
    assert reopened.kernel.drawing_datum_identifiers == (updated,)
