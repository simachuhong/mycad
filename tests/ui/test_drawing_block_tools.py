# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Derived block display data remain separate from editable sketch members."""

from collections.abc import Callable
from dataclasses import replace
from typing import Literal, cast
from uuid import uuid4

import pytest

from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
from mycad.core.drawing_text import DrawingText, TextStyleTable
from mycad.core.sketch import LineEntity, Point2D, WorkPlaneFrame
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.ui.drawing_block_tools import DrawingBlockViewCache

_SESSION_FIELD = "_session_id"
_SNAP_METHOD = "_snap_candidates"
_REFERENCE_SNAP_METHOD = "_reference_snap_candidates"
_SYNC_METHOD = "_sync_drawing_layers"
_TRANSFORM_METHOD = "_transform_point"
_PREVIEW_FIELD = "_collection_transform_preview"
_BLOCK_HIT_METHOD = "_hit_block_at"
_PROJECT_RASTER = "_project_raster"
_DRAW_COLLECTION_PREVIEW = "_draw_collection_preview"
_CENTER_TANGENT_SNAP_METHOD = "_center_tangent_snap_candidates"
_FIRST_POINT_FIELD = "_first"


def _skip_gl_paint(*_args: object, **_kwargs: object) -> None:
    pass


def test_block_view_projects_once_and_keeps_instance_and_member_layers() -> None:
    first = LineEntity(uuid4().hex, (1, 0), (2, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 2), layer_name="Other")
    text = DrawingText(uuid4().hex, "T", (1, 1), layer_name="Other")
    definition = BlockDefinition(uuid4().hex, "B", (first, second), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 20), 90, 2, "Insert")
    layers = SketchLayerTable().add(SketchLayer("Other")).add(SketchLayer("Insert"))
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    cache = DrawingBlockViewCache()
    view = cache.build((definition,), (instance,), layers, TextStyleTable(), frame)
    assert len(view.geometry) == 2 and len(view.texts) == 1
    item = view.geometry[0]
    assert item.instance_id == instance.instance_id and item.pickable
    assert isinstance(item.entity, LineEntity)
    assert item.entity.start_mm == pytest.approx((22, -10))
    assert item.layer.name == "Insert" and view.geometry[1].layer.name == "Other"
    assert view.texts[0].instance_id == instance.instance_id
    assert view.texts[0].text.position_mm == pytest.approx((22, -8))
    assert cache.build((definition,), (instance,), layers, TextStyleTable(), frame) is view
    changed = replace(instance, insertion_mm=(11, 20))
    assert cache.build((definition,), (changed,), layers, TextStyleTable(), frame) is not view


@pytest.mark.parametrize("plane", ["parallel", "tilted"])
def test_block_view_skips_non_coplanar_frame_and_restores_on_return(plane: str) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (1, 0))
    text = DrawingText(uuid4().hex, "A", (0, 1))
    definition = BlockDefinition(uuid4().hex, "B", (line,), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (3, 4))
    layers, styles = SketchLayerTable(), TextStyleTable()
    frame = (
        replace(WorkPlaneFrame.xy(), origin_mm=(0, 0, 2))
        if plane == "parallel"
        else WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, 0, 1), (0, -1, 0))
    )
    cache = DrawingBlockViewCache()
    view = cache.build((definition,), (instance,), layers, styles, WorkPlaneFrame.xy())
    assert len(view.geometry) == len(view.texts) == 1
    off_plane = cache.build((definition,), (instance,), layers, styles, frame)
    assert off_plane.geometry == off_plane.texts == ()
    restored = cache.build((definition,), (instance,), layers, styles, WorkPlaneFrame.xy())
    assert restored == view


def test_block_view_honors_both_instance_and_effective_member_layers() -> None:
    first = LineEntity(uuid4().hex, (0, 0), (1, 0))
    second = LineEntity(uuid4().hex, (0, 1), (1, 1), layer_name="Other")
    definition = BlockDefinition(uuid4().hex, "B", (first, second), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), layer_name="Insert")
    layers = SketchLayerTable().add(SketchLayer("Other")).add(SketchLayer("Insert"))
    cache = DrawingBlockViewCache()
    hidden_member = layers.replace(replace(layers.get("Other"), visible=False))
    assert (
        len(
            cache.build(
                (definition,), (instance,), hidden_member, TextStyleTable(), WorkPlaneFrame.xy()
            ).geometry
        )
        == 1
    )
    hidden_instance = layers.replace(replace(layers.get("Insert"), frozen=True))
    assert (
        cache.build(
            (definition,), (instance,), hidden_instance, TextStyleTable(), WorkPlaneFrame.xy()
        ).geometry
        == ()
    )
    locked_member = layers.replace(replace(layers.get("Other"), locked=True))
    geometry = cache.build(
        (definition,), (instance,), locked_member, TextStyleTable(), WorkPlaneFrame.xy()
    ).geometry
    assert geometry[0].pickable and not geometry[1].pickable
    locked_instance = layers.replace(replace(layers.get("Insert"), locked=True))
    assert not any(
        item.pickable
        for item in cache.build(
            (definition,), (instance,), locked_instance, TextStyleTable(), WorkPlaneFrame.xy()
        ).geometry
    )


@pytest.mark.parametrize("direction", ["horizontal", "diagonal", "offscreen"])
def test_canvas_clips_visible_extremely_large_block_line(qtbot: object, direction: str) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    baseline = canvas.grab().toImage()
    endpoints = {
        "horizontal": ((0.0, 0.0), (1e10, 0.0)),
        "diagonal": ((-1e10, -1e10), (2e10, 2e10)),
        "offscreen": ((-1e10, 1e10), (1e10, 1e10)),
    }
    line = LineEntity(uuid4().hex, *endpoints[direction])
    definition = BlockDefinition(uuid4().hex, "Large", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), scale=1e10)
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    rendered = canvas.grab().toImage()
    center = canvas.local_to_screen((0, 0))
    y = center.y() - 40 if direction == "diagonal" else center.y()
    changed = any(
        rendered.pixelColor(x, py) != baseline.pixelColor(x, py)
        for x in range(center.x() + (30 if direction == "horizontal" else 37), center.x() + 60)
        for py in range(y - 3, y + 4)
    )
    assert changed is (direction != "offscreen")


@pytest.mark.parametrize("kind", ["point", "rectangle"])
def test_canvas_renders_large_block_point_or_rectangle(qtbot: object, kind: str) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import PointEntity, RectangleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    baseline = canvas.grab().toImage()
    entity = (
        PointEntity(uuid4().hex, (1e20, 1e20))
        if kind == "point"
        else RectangleEntity(uuid4().hex, (0, 0), (1e20, 1e20))
    )
    definition = BlockDefinition(uuid4().hex, "Large", (entity,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    rendered = canvas.grab().toImage()
    center = canvas.local_to_screen((0, 0))
    changed = any(
        rendered.pixelColor(x, y) != baseline.pixelColor(x, y)
        for x in range(center.x() + 30, center.x() + 60)
        for y in range(center.y() - 2, center.y() + 3)
    )
    assert changed is (kind == "rectangle")


@pytest.mark.parametrize("kind", ["circle", "arc"])
def test_canvas_skips_offscreen_large_block_circle_or_arc(qtbot: object, kind: str) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import ArcEntity, CircleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    baseline = canvas.grab().toImage()
    entity = (
        CircleEntity(uuid4().hex, (1e20, 1e20), 100)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (1e20, 1e20), 100, 0, 90)
    )
    definition = BlockDefinition(uuid4().hex, "Far", (entity,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    rendered = canvas.grab().toImage()
    center = canvas.local_to_screen((0, 0))
    assert all(
        rendered.pixelColor(x, y) == baseline.pixelColor(x, y)
        for x in range(center.x() + 30, center.x() + 60)
        for y in range(center.y() - 2, center.y() + 3)
    )


@pytest.mark.parametrize("kind", ["circle", "arc", "reverse_arc", "outside_arc"])
def test_canvas_renders_visible_tangent_of_large_block_circle(qtbot: object, kind: str) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import ArcEntity, CircleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    baseline = canvas.grab().toImage()
    angles = {"arc": (135, 90), "reverse_arc": (225, -90), "outside_arc": (0, 90)}
    entity = (
        CircleEntity(uuid4().hex, (1e20, 0), 1e20)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (1e20, 0), 1e20, *angles[kind])
    )
    definition = BlockDefinition(uuid4().hex, "Tangent", (entity,), ())
    canvas.set_drawing_blocks(
        (definition,),
        (BlockInstance(uuid4().hex, definition.definition_id, (0, 0)),),
        TextStyleTable(),
    )
    rendered = canvas.grab().toImage()
    center = canvas.local_to_screen((0, 0))
    changed = any(
        rendered.pixelColor(x, y) != baseline.pixelColor(x, y)
        for x in range(center.x() - 3, center.x() + 4)
        for y in range(center.y() - 60, center.y() - 30)
    )
    assert changed is (kind != "outside_arc")


@pytest.mark.parametrize("kind", ["circle", "arc", "outside_arc"])
def test_large_block_circle_pick_distinguishes_visible_edge_from_nearby_space(
    qtbot: object, kind: str
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import ArcEntity, CircleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    entity = (
        CircleEntity(uuid4().hex, (1e20, 0), 1e20)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (1e20, 0), 1e20, 0 if kind == "outside_arc" else 135, 90)
    )
    definition = BlockDefinition(uuid4().hex, "Tangent", (entity,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    hit = cast("Callable[[Point2D], str | None]", getattr(canvas, _BLOCK_HIT_METHOD))
    assert hit((0, 0)) == (None if kind == "outside_arc" else instance.instance_id)
    assert hit((20, 0)) is None


@pytest.mark.parametrize("selected", [False, True])
def test_canvas_skips_offscreen_large_block_text_with_selection(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, selected: bool
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    text = DrawingText(uuid4().hex, "Far", (1e20, 1e20))
    definition = BlockDefinition(uuid4().hex, "Far", (), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    editor.canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    if selected:
        editor.canvas.selected_block_instance_ids = {instance.instance_id}
    editor.canvas.grab()
    assert editor.canvas.selected_block_instance_ids == (
        {instance.instance_id} if selected else set()
    )


@pytest.mark.parametrize("height", [1e10, 1e200])
@pytest.mark.parametrize("glyph", ["I", "O"])
def test_canvas_renders_visible_portion_of_extremely_large_block_text(
    qtbot: object, height: float, glyph: str
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.ui.drawing_text_tools import DrawingTextTools
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    DrawingTextTools(canvas)
    baseline = canvas.grab().toImage()
    text = DrawingText(uuid4().hex, glyph, (0, 0), height_mm=height, align="center")
    definition = BlockDefinition(uuid4().hex, "LargeText", (), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    rendered = canvas.grab().toImage()
    origin = canvas.local_to_screen((0, 0))
    changed = sum(
        rendered.pixel(x, y) != baseline.pixel(x, y)
        for x in range(origin.x() - 10, origin.x() + 11)
        for y in range(origin.y() - 60, origin.y() - 10)
    )
    assert changed > 100


def test_extremely_large_block_text_preserves_glyph_hole(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.ui.drawing_text_tools import DrawingTextTools
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    DrawingTextTools(canvas)
    baseline = canvas.grab().toImage()
    text = DrawingText(uuid4().hex, "O", (0, 0), height_mm=1e200, align="middle_center")
    definition = BlockDefinition(uuid4().hex, "LargeTextHole", (), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    rendered = canvas.grab().toImage()
    origin = canvas.local_to_screen((0, 0))
    assert rendered.pixel(origin.x(), origin.y()) == baseline.pixel(origin.x(), origin.y())


@pytest.mark.parametrize("rotation", [45.0, 90.0])
def test_extremely_large_rotated_block_text_is_visible(qtbot: object, rotation: float) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.ui.drawing_text_tools import DrawingTextTools
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    DrawingTextTools(canvas)
    baseline = canvas.grab().toImage()
    text = DrawingText(uuid4().hex, "I", (0, 0), height_mm=1e200, align="center")
    definition = BlockDefinition(uuid4().hex, "RotatedLargeText", (), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), rotation_deg=rotation)
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    rendered = canvas.grab().toImage()
    origin = canvas.local_to_screen((0, 0))
    changed = sum(
        rendered.pixel(x, y) != baseline.pixel(x, y)
        for x in range(origin.x() - 60, origin.x() + 61)
        for y in range(origin.y() - 60, origin.y() + 61)
    )
    assert changed > 100


def test_canvas_renders_staged_block_and_snaps_without_exposing_geometry(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QPainter
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch import Sketch
    from mycad.ui.drawing_collection_session import DrawingCollectionSession
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=cast("int", getattr(window, _SESSION_FIELD)),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local")
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local")
    )
    view = editor.canvas.drawing_block_view()
    assert len(view.geometry) == 1 and view.geometry[0].instance_id == instance.instance_id
    derived = view.geometry[0].entity
    assert derived not in editor.canvas.selectable_entities()
    assert derived not in editor.canvas.visible_snap_entities()
    snap_candidates = cast(
        "Callable[[], list[tuple[Point2D, str]]]", getattr(editor.canvas, _SNAP_METHOD)
    )
    assert ((10, 10), "端点") in snap_candidates()
    drawn: list[str] = []

    def record(_painter: QPainter, entity: object, **_kwargs: object) -> None:
        if isinstance(entity, LineEntity):
            drawn.append(entity.entity_id)

    monkeypatch.setattr(editor.canvas, "_draw_entity", record)
    editor.canvas.grab()
    assert derived.entity_id in drawn
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.drawing_block_view().geometry == ()
    assert ((10, 10), "端点") not in snap_candidates()


def test_canvas_switching_workplanes_hides_block_rendering_and_snaps(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QPainter
    from pytestqt.qtbot import QtBot

    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    snap_candidates = cast("Callable[[], list[tuple[Point2D, str]]]", getattr(canvas, _SNAP_METHOD))
    assert ((10, 10), "端点") in snap_candidates()
    canvas.selected_block_instance_ids = {instance.instance_id}
    rotated = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), rotated)
    assert canvas.selected_block_instance_ids == {instance.instance_id}
    drawn: list[str] = []

    def record(_painter: QPainter, entity: object, **_kwargs: object) -> None:
        if isinstance(entity, LineEntity):
            drawn.append(entity.entity_id)

    monkeypatch.setattr(canvas, "_draw_entity", record)
    off_plane = replace(WorkPlaneFrame.xy(), origin_mm=(0, 0, 2))
    canvas.set_background_sketches((), off_plane)
    canvas.grab()
    assert drawn == [] and ((10, 10), "端点") not in snap_candidates()
    assert canvas.selected_block_instance_ids == set()
    canvas.set_background_sketches((), WorkPlaneFrame.xy())
    canvas.grab()
    assert drawn and ((10, 10), "端点") in snap_candidates()
    assert canvas.selected_block_instance_ids == set()


@pytest.mark.parametrize(
    "restriction", ["instance_hidden", "members_hidden", "partial", "locked", "document_switch"]
)
def test_block_selection_tracks_layer_visibility(qtbot: object, restriction: str) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    layers = (
        SketchLayerTable()
        .add(SketchLayer("Insert"))
        .add(SketchLayer("First"))
        .add(SketchLayer("Second"))
    )
    canvas.set_layer_table(layers, "0")
    first = LineEntity(uuid4().hex, (0, 0), (1, 0), layer_name="First")
    second = LineEntity(uuid4().hex, (0, 1), (1, 1), layer_name="Second")
    definition = BlockDefinition(uuid4().hex, "B", (first, second), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), layer_name="Insert")
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    canvas.selected_block_instance_ids = {instance.instance_id}
    if restriction == "instance_hidden":
        updated = layers.replace(replace(layers.get("Insert"), visible=False))
    elif restriction == "members_hidden":
        updated = layers.replace(replace(layers.get("First"), visible=False))
        updated = updated.replace(replace(updated.get("Second"), frozen=True))
    elif restriction == "partial":
        updated = layers.replace(replace(layers.get("First"), visible=False))
    elif restriction == "document_switch":
        updated = SketchLayerTable()
    else:
        updated = layers.replace(replace(layers.get("Insert"), locked=True))
    canvas.set_layer_table(updated, "0")
    expected: set[str] = {instance.instance_id} if restriction in {"partial", "locked"} else set()
    assert canvas.selected_block_instance_ids == expected


def test_fit_view_includes_visible_block_geometry(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (1000, 1000))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    canvas.fit_view()
    assert canvas.rect().contains(canvas.local_to_screen((1000, 1000)))
    assert canvas.rect().contains(canvas.local_to_screen((1020, 1000)))


@pytest.mark.parametrize("background", [False, True])
def test_fit_view_includes_ellipse_and_block(qtbot: object, background: bool) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import EllipseEntity, Sketch
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    ellipse = EllipseEntity(uuid4().hex, (1000, 1000), 20, 10, rotation_deg=30)
    if background:
        canvas.set_background_sketches(
            (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (ellipse,)),), WorkPlaneFrame.xy()
        )
    else:
        assert canvas.replace_draft_entities((ellipse,))
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (20, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (-1000, -1000))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    canvas.fit_view()
    assert canvas.rect().contains(canvas.local_to_screen(instance.insertion_mm))
    assert all(
        canvas.rect().contains(canvas.local_to_screen(point)) for point in ellipse.sampled_points()
    )


@pytest.mark.parametrize("restriction", ["hidden", "frozen"])
def test_fit_view_uses_actual_layer_for_same_id_background_geometry(
    qtbot: object, restriction: str
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import Sketch
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    layers = SketchLayerTable().add(
        SketchLayer("Restricted", visible=restriction != "hidden", frozen=restriction == "frozen")
    )
    identity = uuid4().hex
    hidden = LineEntity(identity, (1e6, 1e6), (1e6 + 20, 1e6), layer_name="Restricted")
    visible = LineEntity(identity, (1000, 1000), (1020, 1000))
    canvas.set_background_sketches(
        (
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (hidden,), layers=layers),
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (visible,), layers=layers),
        ),
        WorkPlaneFrame.xy(),
    )
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (20, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (-1000, -1000))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    canvas.fit_view()
    assert canvas.rect().contains(canvas.local_to_screen(instance.insertion_mm))
    assert canvas.rect().contains(canvas.local_to_screen(visible.start_mm))
    assert canvas.rect().contains(canvas.local_to_screen(visible.end_mm))
    assert not canvas.rect().contains(canvas.local_to_screen(hidden.start_mm))


@pytest.mark.parametrize("mirrored", [False, True])
def test_fit_view_includes_rotated_picture_and_block(qtbot: object, mirrored: bool) -> None:
    import math

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from pytestqt.qtbot import QtBot

    from mycad.ui.drawing_clipboard import raster_from_clipboard_image
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    layers = SketchLayerTable().add(SketchLayer("Hidden", visible=False))
    canvas.set_layer_table(layers, "0")
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    picture = replace(
        raster_from_clipboard_image(image, "0", None),
        origin_mm=(1000, 1000),
        width_mm=200,
        height_mm=100,
        angle_deg=45,
        mirrored=mirrored,
    )
    hidden = replace(picture, image_id=uuid4().hex, layer_name="Hidden", origin_mm=(1e6, 1e6))
    canvas.set_drawing_rasters((picture, hidden))
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (20, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (-1000, -1000))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    canvas.fit_view()
    angle = math.radians(picture.angle_deg)
    u = (math.cos(angle) * picture.width_mm, math.sin(angle) * picture.width_mm)
    direction = -1 if mirrored else 1
    v = (
        -math.sin(angle) * picture.height_mm * direction,
        math.cos(angle) * picture.height_mm * direction,
    )
    x, y = picture.origin_mm
    corners = (
        (x, y),
        (x + u[0], y + u[1]),
        (x + v[0], y + v[1]),
        (x + u[0] + v[0], y + u[1] + v[1]),
    )
    assert canvas.rect().contains(canvas.local_to_screen(instance.insertion_mm))
    assert all(canvas.rect().contains(canvas.local_to_screen(point)) for point in corners)
    assert not canvas.rect().contains(canvas.local_to_screen(hidden.origin_mm))


def test_rotated_work_plane_projects_picture_for_display_fit_and_selection(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    picture = replace(
        raster_from_clipboard_image(image, "0", None),
        origin_mm=(20, 0),
        width_mm=10,
        height_mm=5,
    )
    canvas.set_drawing_rasters((picture,))
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (-20, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    canvas.fit_view()
    drawn: list[DrawingRaster] = []
    original = cast("Callable[..., None]", vars(type(canvas))["_draw_raster"])

    def record(
        target: SketchCanvas, painter: QPainter, raster: DrawingRaster, **kwargs: object
    ) -> None:
        drawn.append(raster)
        original(target, painter, raster, **kwargs)

    monkeypatch.setattr(SketchCanvas, "_draw_raster", record)
    canvas.show()
    canvas.grab()
    assert drawn and drawn[-1].origin_mm == pytest.approx((0, -20))
    assert drawn[-1].angle_deg == pytest.approx(-90)
    assert canvas.rect().contains(canvas.local_to_screen((2, -22)))
    assert canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((2, -22)))
    assert canvas.selected_raster_ids == {picture.image_id}
    canvas.selected_raster_ids.clear()
    for point in ((-1, -19), (6, -31)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.selected_raster_ids == {picture.image_id}
    off_plane = replace(frame, origin_mm=(0, 0, 2))
    canvas.set_background_sketches((), off_plane)
    assert not canvas.selected_raster_ids
    drawn.clear()
    canvas.grab()
    assert not drawn
    assert canvas.drawing_rasters == (picture,)


def test_picture_projection_cache_refreshes_for_frame_and_image_changes(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from pytestqt.qtbot import QtBot

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    picture = replace(raster_from_clipboard_image(image, "0", None), origin_mm=(20, 0))
    canvas.set_drawing_rasters((picture,))
    calls: list[DrawingRaster] = []
    original = cast(
        "Callable[[DrawingRaster, WorkPlaneFrame, WorkPlaneFrame], DrawingRaster]",
        getattr(SketchCanvas, _PROJECT_RASTER),
    )

    def record(
        raster: DrawingRaster, source: WorkPlaneFrame, target: WorkPlaneFrame
    ) -> DrawingRaster:
        calls.append(raster)
        return original(raster, source, target)

    monkeypatch.setattr(SketchCanvas, "_project_raster", staticmethod(record))
    canvas.show()
    canvas.fit_view()
    canvas.grab()
    canvas.grab()
    assert calls == [picture]
    canvas.set_background_sketches((), replace(frame, origin_mm=(1, 0, 0)))
    canvas.grab()
    assert calls == [picture, picture]
    changed = replace(picture, origin_mm=(30, 0))
    canvas.set_drawing_rasters((changed,))
    canvas.grab()
    assert calls == [picture, picture, changed]


@pytest.mark.parametrize("action", ["move", "scale", "rotate"])
def test_rotated_work_plane_transforms_picture_in_drawing_coordinates(
    qtbot: object, action: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from pytestqt.qtbot import QtBot

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    picture = replace(
        raster_from_clipboard_image(image, "0", None), origin_mm=(20, 0), angle_deg=300
    )
    canvas.set_drawing_rasters((picture,))
    canvas.selected_raster_ids = {picture.image_id}
    committed: list[DrawingRaster] = []
    canvas.commit_raster_edit = lambda _action, result: committed.append(result)
    canvas.begin_transform(action)
    canvas.add_coordinate_point((2, 3), exact_point=True)
    preview_point = {"move": (2.0, 5.0), "scale": (4.0, 3.0), "rotate": (2.0, 4.0)}[action]
    transform = cast("Callable[..., None]", getattr(type(canvas), _TRANSFORM_METHOD))
    transform(canvas, preview_point, commit=False)
    previews = cast("tuple[DrawingRaster, ...]", vars(canvas)["_raster_transform_previews"])
    assert len(previews) == 1
    if action == "move":
        canvas.add_coordinate_point((2, 5), exact_point=True)
        expected = (18, 0)
    elif action == "scale":
        assert canvas.apply_scale_factor(2)
        expected = (43, -2)
    else:
        assert canvas.apply_rotation_angle(90)
        expected = (-1, 25)
    assert len(committed) == 1
    assert committed[0].origin_mm == pytest.approx(expected)
    assert committed[0].angle_deg == (390 if action == "rotate" else 300)
    assert previews[0].origin_mm == pytest.approx(
        frame.world_to_local(WorkPlaneFrame.xy().local_to_world(committed[0].origin_mm))
    )


@pytest.mark.parametrize("action", ["move", "copy", "scale", "rotate", "mirror"])
def test_rotated_work_plane_transforms_picture_with_draft_geometry(
    qtbot: object, action: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from pytestqt.qtbot import QtBot

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.sketch import SketchEntity
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    picture = replace(raster_from_clipboard_image(image, "0", None), origin_mm=(20, 0))
    canvas.set_drawing_rasters((picture,))
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_raster_ids = {picture.image_id}
    canvas.selected_entity_ids = {line.entity_id}
    committed: list[tuple[tuple[SketchEntity, ...], tuple[DrawingRaster, ...], str]] = []
    canvas.commit_mixed_draft_transform = lambda entities, rasters, operation: (
        committed.append((entities, rasters, operation)) or "done"
    )
    canvas.begin_transform(action, ask_mirror_erase=action == "mirror")
    canvas.add_coordinate_point((2, 3), exact_point=True)
    preview_point = {
        "move": (2.0, 5.0),
        "copy": (2.0, 5.0),
        "scale": (4.0, 3.0),
        "rotate": (2.0, 4.0),
        "mirror": (2.0, 5.0),
    }[action]
    transform = cast("Callable[..., None]", getattr(type(canvas), _TRANSFORM_METHOD))
    transform(canvas, preview_point, commit=False)
    previews = cast("tuple[DrawingRaster, ...]", vars(canvas)["_raster_transform_previews"])
    assert len(previews) == 1
    if action in {"move", "copy"}:
        canvas.add_coordinate_point((2, 5), exact_point=True)
        expected = (18, 0)
    elif action == "scale":
        assert canvas.apply_scale_factor(2)
        expected = (43, -2)
    elif action == "rotate":
        assert canvas.apply_rotation_angle(90)
        expected = (-1, 25)
    else:
        canvas.add_coordinate_point((2, 5), exact_point=True)
        assert canvas.confirm_mirror_erase(False)
        expected = (20, 4)
    assert len(committed) == 1
    assert committed[0][1][0].origin_mm == pytest.approx(expected)
    assert committed[0][2] == ("add" if action in {"copy", "mirror"} else "update")
    assert previews[0].origin_mm == pytest.approx(
        frame.world_to_local(WorkPlaneFrame.xy().local_to_world(committed[0][1][0].origin_mm))
    )


def test_opposite_work_plane_projects_and_rotates_image_without_losing_orientation(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from pytestqt.qtbot import QtBot

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (1, 0, 0), (0, 0, -1))
    canvas.set_background_sketches((), frame)
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    picture = replace(
        raster_from_clipboard_image(image, "0", None), origin_mm=(20, 0), angle_deg=20
    )
    canvas.set_drawing_rasters((picture,))
    drawn: list[DrawingRaster] = []
    original = cast("Callable[..., None]", vars(SketchCanvas)["_draw_raster"])

    def record(
        target: SketchCanvas, painter: QPainter, raster: DrawingRaster, **kwargs: object
    ) -> None:
        drawn.append(raster)
        original(target, painter, raster, **kwargs)

    monkeypatch.setattr(SketchCanvas, "_draw_raster", record)
    canvas.show()
    canvas.grab()
    assert drawn[-1].origin_mm == pytest.approx((0, 20))
    assert drawn[-1].angle_deg == pytest.approx(70)
    assert drawn[-1].mirrored
    canvas.selected_raster_ids = {picture.image_id}
    committed: list[DrawingRaster] = []
    canvas.commit_raster_edit = lambda _action, result: committed.append(result)
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((2, 3), exact_point=True)
    assert canvas.apply_rotation_angle(90)
    assert committed[0].origin_mm == pytest.approx((1, -15))
    assert committed[0].angle_deg == -70
    assert not committed[0].mirrored


def test_rotated_work_plane_pastes_image_in_drawing_coordinates(qtbot: object) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    QApplication.clipboard().setImage(image)
    committed: list[DrawingRaster] = []
    canvas.commit_clipboard_raster = lambda raster: committed.append(raster)
    try:
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point((2, 3), exact_point=True)
        assert len(committed) == 1
        assert committed[0].origin_mm == pytest.approx((-3, 2))
        assert committed[0].angle_deg == pytest.approx(90)
    finally:
        QApplication.clipboard().clear()


def test_rotated_work_plane_copies_single_picture_without_changing_its_angle(qtbot: object) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    picture = replace(
        raster_from_clipboard_image(image, "0", None), origin_mm=(20, 0), angle_deg=20
    )
    canvas.set_drawing_rasters((picture,))
    canvas.selected_raster_ids = {picture.image_id}
    committed: list[DrawingRaster] = []
    canvas.commit_clipboard_raster = lambda raster: committed.append(raster)
    try:
        assert canvas.copy_to_clipboard() and canvas.begin_clipboard_paste()
        canvas.add_coordinate_point((2, 3), exact_point=True)
        assert len(committed) == 1
        assert committed[0].origin_mm == pytest.approx((-3, 2))
        assert committed[0].angle_deg == pytest.approx(20)
    finally:
        QApplication.clipboard().clear()


def test_rotated_work_plane_pastes_legacy_picture_group(qtbot: object) -> None:
    from PySide6.QtCore import QByteArray, QMimeData, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.ui.drawing_clipboard import (
        DRAWING_RASTER_GROUP_MIME,
        encode_raster_group,
        raster_from_clipboard_image,
    )
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    first = replace(raster_from_clipboard_image(image, "0", None), origin_mm=(20, 0))
    second = replace(first, image_id=uuid4().hex, origin_mm=(25, 0))
    mime = QMimeData()
    mime.setData(DRAWING_RASTER_GROUP_MIME, QByteArray(encode_raster_group((first, second))))
    QApplication.clipboard().setMimeData(mime)
    committed: list[tuple[DrawingRaster, ...]] = []
    canvas.commit_raster_batch = lambda _action, images: committed.append(images)
    try:
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point((2, 3), exact_point=True)
        assert len(committed) == 1 and len(committed[0]) == 2
        assert committed[0][0].origin_mm == pytest.approx((-3, 2))
        assert committed[0][1].origin_mm == pytest.approx((2, 2))
        assert all(item.angle_deg == pytest.approx(0, abs=1e-12) for item in committed[0])
    finally:
        QApplication.clipboard().clear()


def test_rotated_work_plane_pastes_legacy_mixed_geometry_and_picture(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QByteArray, QMimeData, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.sketch import Sketch, SketchEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.drawing_clipboard import (
        DRAWING_MIXED_CLIPBOARD_MIME,
        encode_mixed_clipboard,
        raster_from_clipboard_image,
    )
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    line = LineEntity(uuid4().hex, (20, 0), (22, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        2,
        "mm",
        position_mm=(21, 3),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    raster = replace(raster_from_clipboard_image(image, "0", None), origin_mm=(20, 0))
    mime = QMimeData()
    mime.setData(
        DRAWING_MIXED_CLIPBOARD_MIME, QByteArray(encode_mixed_clipboard(sketch, (raster,)))
    )
    QApplication.clipboard().setMimeData(mime)
    committed: list[tuple[Sketch, tuple[DrawingRaster, ...]]] = []
    canvas.commit_mixed_clipboard = lambda data, images, _styles, _fonts: committed.append(
        (data, images)
    )
    drawn_geometry: list[SketchEntity] = []
    drawn_rasters: list[DrawingRaster] = []
    original_entity = cast("Callable[..., None]", vars(SketchCanvas)["_draw_entity"])
    original_raster = cast("Callable[..., None]", vars(SketchCanvas)["_draw_raster"])

    def record_entity(
        target: SketchCanvas, painter: QPainter, item: SketchEntity, **kwargs: object
    ) -> None:
        drawn_geometry.append(item)
        original_entity(target, painter, item, **kwargs)

    def record_raster(
        target: SketchCanvas, painter: QPainter, item: DrawingRaster, **kwargs: object
    ) -> None:
        drawn_rasters.append(item)
        original_raster(target, painter, item, **kwargs)

    monkeypatch.setattr(SketchCanvas, "_draw_entity", record_entity)
    monkeypatch.setattr(SketchCanvas, "_draw_raster", record_raster)
    try:
        assert canvas.begin_clipboard_paste()
        monkeypatch.setattr(canvas, "_cursor", (5.0, 7.0))
        canvas.show()
        canvas.grab()
        assert drawn_rasters[-1].origin_mm == pytest.approx((5, 7))
        assert drawn_rasters[-1].angle_deg == pytest.approx(-90)
        assert drawn_geometry and isinstance(drawn_geometry[-1], LineEntity)
        assert drawn_geometry[-1].start_mm == pytest.approx((5, 7))
        assert drawn_geometry[-1].end_mm == pytest.approx((5, 5))
        canvas.add_coordinate_point((5, 7), exact_point=True)
        assert len(committed) == 1
        placed, images = committed[0]
        assert placed.frame == WorkPlaneFrame.xy()
        assert isinstance(placed.entities[0], LineEntity)
        assert placed.entities[0].start_mm == pytest.approx((-7, 5))
        assert placed.constraints[0].position_mm == pytest.approx((-6, 8))
        assert placed.constraints[0].references[0].entity_id == placed.entities[0].entity_id
        assert images[0].origin_mm == pytest.approx((-7, 5))
    finally:
        QApplication.clipboard().clear()


def test_rotated_legacy_mixed_paste_reopens_with_geometry_and_image_aligned(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    from pathlib import Path

    from PySide6.QtCore import QByteArray, QMimeData, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch
    from mycad.ui.drawing_clipboard import (
        DRAWING_MIXED_CLIPBOARD_MIME,
        encode_mixed_clipboard,
        raster_from_clipboard_image,
    )
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: frame)
    editor.canvas.set_background_sketches((), frame)
    line = LineEntity(uuid4().hex, (20, 0), (22, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    raster = replace(raster_from_clipboard_image(image, "0", None), origin_mm=(20, 0))
    mime = QMimeData()
    mime.setData(
        DRAWING_MIXED_CLIPBOARD_MIME, QByteArray(encode_mixed_clipboard(sketch, (raster,)))
    )
    QApplication.clipboard().setMimeData(mime)
    try:
        assert editor.canvas.begin_clipboard_paste()
        editor.canvas.add_coordinate_point((5, 7), exact_point=True)
        assert len(services.kernel.sketches) == len(services.kernel.drawing_rasters) == 1
        stored = services.kernel.sketches[0]
        assert stored.frame == WorkPlaneFrame.xy()
        assert isinstance(stored.entities[0], LineEntity)
        assert stored.entities[0].start_mm == pytest.approx((-7, 5))
        assert services.kernel.drawing_rasters[0].origin_mm == pytest.approx((-7, 5))
        path = cast("Path", tmp_path) / "mixed-rotated.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert services.kernel.sketches == (stored,)
        reopened.bus.undo_operation()
        assert services.kernel.sketches == services.kernel.drawing_rasters == ()
        reopened.bus.redo_operation()
        assert services.kernel.sketches == (stored,) and len(services.kernel.drawing_rasters) == 1
    finally:
        QApplication.clipboard().clear()


@pytest.mark.parametrize("reversed_normal", [False, True])
def test_collection_angular_dimension_preview_projects_coplanar_plane(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, reversed_normal: bool
) -> None:
    from PySide6.QtGui import QImage, QPainter
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.ui.geometric_tolerance_tools import GeometricToleranceTools
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    frame = (
        WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
        if reversed_normal
        else WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    canvas.set_background_sketches((), frame)
    item = DetachedDimension(
        uuid4().hex, "angular_3p", (10, 0), (0, 10), (5, 5), 0, 90, vertex_mm=(0, 0)
    )
    payload = DrawingCollectionClipboard(
        (), (), (), (), TextStyleTable(), reference_dimensions=(item,)
    )
    rendered: list[DetachedDimension] = []

    def record(
        _self: GeometricToleranceTools,
        _painter: QPainter,
        value: object,
        *_rest: object,
        **_kwargs: object,
    ) -> None:
        if isinstance(value, DetachedDimension):
            rendered.append(value)

    monkeypatch.setattr(GeometricToleranceTools, "draw_clipboard_preview", record)
    image = QImage(600, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        cast("Callable[..., None]", getattr(canvas, _DRAW_COLLECTION_PREVIEW))(
            painter, payload, (3, 4)
        )
    finally:
        painter.end()
    assert len(rendered) == 1
    assert rendered[0].angle_deg == 0 and rendered[0].nominal == 90
    assert rendered[0].first_mm == pytest.approx((3, -6))


@pytest.mark.parametrize("kind", ["rotated", "aligned", "radius", "ordinate_x", "ordinate_y"])
@pytest.mark.parametrize("reflected", [False, True])
def test_reference_dimension_projection_preserves_measurement(kind: str, reflected: bool) -> None:
    import math

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.detached_dimension_layout import project_reference_dimension

    nominal = {
        "rotated": 2.0,
        "aligned": math.sqrt(13),
        "radius": math.sqrt(13),
        "ordinate_x": 2.0,
        "ordinate_y": 3.0,
    }[kind]
    item = DetachedDimension(uuid4().hex, kind, (0, 0), (2, 3), (5, 7), 0, nominal)
    target = (
        WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
        if reflected
        else WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    result = project_reference_dimension(item, WorkPlaneFrame.xy(), target)
    assert result.nominal == pytest.approx(item.nominal)
    assert target.local_to_world(result.first_mm) == pytest.approx((0, 0, 0))
    assert target.local_to_world(result.second_mm) == pytest.approx((2, 3, 0))


def test_rotated_reference_dimension_display_and_selection(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.detached_dimension_layout import layout_reference_dimension
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    dimension = DetachedDimension(uuid4().hex, "rotated", (10, 0), (20, 0), (15, 5), 0, 10)
    tools.sync((), (), (dimension,))
    projected = replace(
        dimension, first_mm=(0, -10), second_mm=(0, -20), location_mm=(5, -15), angle_deg=-90
    )
    expected = layout_reference_dimension(projected, canvas).label
    assert tools.reference_bounds(dimension) == expected
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=expected.center().toPoint())
    assert tools.selected_id == dimension.dimension_id
    tools.selected_ids.clear()
    tools.selection_original.clear()
    bounds = expected.adjusted(-200, -200, 200, 200)
    tools.select_box(bounds.topLeft(), bounds.bottomRight(), Qt.KeyboardModifier.NoModifier)
    assert dimension.dimension_id in tools.selected_ids
    extent = tools.visible_extent_points()
    assert any(point == pytest.approx((0, -10)) for point in extent)
    assert any(point == pytest.approx((0, -20)) for point in extent)
    canvas.set_background_sketches((), replace(WorkPlaneFrame.xy(), origin_mm=(0, 0, 1)))
    assert tools.reference_bounds(dimension).isEmpty()
    assert dimension.dimension_id not in tools.selected_ids
    assert tools.selected_id is None


@pytest.mark.parametrize(
    ("angle", "nominal", "line_count"),
    [(0, 2, 1), (45, 5 / 2**0.5, 2)],
    ids=["straight", "bent"],
)
def test_rotated_ordinate_reference_keeps_its_leader(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, angle: float, nominal: float, line_count: int
) -> None:
    import math

    from PySide6.QtGui import QImage, QPainter
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.ui import geometric_tolerance_tools
    from mycad.ui.detached_dimension_layout import ReferenceDimensionLayout
    from mycad.ui.main_window import MainWindow
    from mycad.ui.sketch_editor import SketchCanvas

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    c, s = (math.cos(math.radians(angle)), math.sin(math.radians(angle))) if angle else (0, 1)
    frame = WorkPlaneFrame((0, 0, 0), (c, s, 0), (-s, c, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    dimension = DetachedDimension(uuid4().hex, "ordinate_x", (0, 0), (2, 3), (5, 7), angle, nominal)
    tools.sync((), (), (dimension,))
    observed: list[ReferenceDimensionLayout] = []
    original = geometric_tolerance_tools.layout_reference_dimension

    def record(
        item: DetachedDimension, target: SketchCanvas, *, ordinate_bent: bool | None = None
    ) -> ReferenceDimensionLayout:
        layout = original(item, target, ordinate_bent=ordinate_bent)
        observed.append(layout)
        return layout

    monkeypatch.setattr(geometric_tolerance_tools, "layout_reference_dimension", record)
    image = QImage(600, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        tools.draw(painter)
    finally:
        painter.end()
    assert len(observed) == 1
    assert len(observed[0].lines) == line_count
    if line_count == 1:
        start, end = observed[0].lines[0]
        assert start == canvas.local_to_screen_precise((3, -2))
        assert end == canvas.local_to_screen_precise((7, -5))
    observed.clear()
    payload = DrawingCollectionClipboard(
        (), (), (), (), TextStyleTable(), reference_dimensions=(dimension,)
    )
    painter = QPainter(image)
    try:
        cast("Callable[..., None]", getattr(canvas, _DRAW_COLLECTION_PREVIEW))(
            painter, payload, (0, 0)
        )
    finally:
        painter.end()
    assert len(observed) == 1 and len(observed[0].lines) == line_count


def test_rotated_reference_dimension_move_uses_drawing_coordinates(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    item = DetachedDimension(uuid4().hex, "rotated", (10, 0), (20, 0), (15, 5), 0, 10)
    assert tools.execute is not None
    assert tools.execute("drawing.reference_dimensions.batch", {"add": [item.to_mapping()]})
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: frame)
    editor.canvas.set_background_sketches((), frame)
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        item.dimension_id,
        "reference",
        {item.dimension_id},
    )
    assert tools.handle_command("MOVE")
    assert tools.handle_command("0,0")
    assert tools.handle_command("5,7")
    changed = services.kernel.drawing_reference_dimensions[0]
    assert changed.first_mm == pytest.approx((3, 5))
    assert changed.second_mm == pytest.approx((13, 5))
    assert changed.location_mm == pytest.approx((8, 10))


def test_rotated_reference_dimension_clipboard_position(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    item = DetachedDimension(uuid4().hex, "rotated", (10, 0), (20, 0), (15, 5), 0, 10)
    assert tools.execute is not None
    assert tools.execute("drawing.reference_dimensions.batch", {"add": [item.to_mapping()]})
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: frame)
    editor.canvas.set_background_sketches((), frame)
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        item.dimension_id,
        "reference",
        {item.dimension_id},
    )
    try:
        assert tools.copy_frame_to_clipboard() and tools.begin_frame_paste()
        QTest.mouseClick(
            editor.canvas,
            Qt.MouseButton.LeftButton,
            pos=editor.canvas.local_to_screen((5, 7)),
        )
        assert len(services.kernel.drawing_reference_dimensions) == 2
        copied = services.kernel.drawing_reference_dimensions[-1]
        assert copied.location_mm == pytest.approx((-7, 5))
        assert copied.first_mm == pytest.approx((-12, 0))
        assert copied.second_mm == pytest.approx((-2, 0))
    finally:
        QApplication.clipboard().clear()


@pytest.mark.parametrize("kind", ["frame", "datum"])
def test_rotated_annotation_move_uses_drawing_coordinates(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, kind: Literal["frame", "datum"]
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 0))
    datum = DatumIdentifier(uuid4().hex, "A", (10, 0), (20, 0))
    source = frame if kind == "frame" else datum
    identity = frame.frame_id if kind == "frame" else datum.datum_id
    assert tools.execute is not None
    key = "add_frames" if kind == "frame" else "add_datums"
    assert tools.execute("drawing.tolerance.batch", {key: [source.to_mapping()]})
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    editor.canvas.set_background_sketches((), view)
    tools.selected_id, tools.selected_kind, tools.selected_ids = identity, kind, {identity}
    assert tools.handle_command("MOVE")
    assert tools.handle_command("0,0")
    assert tools.handle_command("5,7")
    result = (
        services.kernel.drawing_tolerance_frames[0]
        if kind == "frame"
        else services.kernel.drawing_datum_identifiers[0]
    )
    assert result.position_mm == pytest.approx((3, 5))
    if isinstance(result, DatumIdentifier):
        assert result.target_mm == pytest.approx((13, 5))


def test_annotation_move_rejects_work_plane_change(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 0))
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        frame.frame_id,
        "frame",
        {frame.frame_id},
    )
    assert tools.handle_command("MOVE") and tools.handle_command("0,0")
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    editor.canvas.set_background_sketches((), view)
    assert tools.handle_command("5,7")
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert not tools.transform_action
    assert "工作平面" in editor.canvas.message


def test_annotation_grip_rejects_work_plane_change(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 0))
    assert tools.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]})
    canvas.set_tool("选择元素")
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {frame.frame_id},
        frame.frame_id,
        "frame",
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    assert tools.frame_grip is not None
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), view)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 7)))
    assert services.kernel.drawing_tolerance_frames == (frame,)
    assert tools.frame_grip is None
    assert "工作平面" in canvas.message


@pytest.mark.parametrize("action", ["COPY", "MOVE"])
def test_mixed_annotation_transform_rejects_work_plane_change(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from PySide6.QtWidgets import QApplication, QInputDialog
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.ui.main_window import MainWindow

    def datum_label(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "B", True

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    monkeypatch.setattr(QInputDialog, "getText", datum_label)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    reference = DetachedDimension(uuid4().hex, "aligned", (0, 0), (10, 0), (0, 5), 0, 10)
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 5))
    assert tools.execute is not None
    assert tools.execute("drawing.reference_dimensions.batch", {"add": [reference.to_mapping()]})
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {reference.dimension_id, datum.datum_id},
        datum.datum_id,
        "datum",
    )
    try:
        assert tools.handle_command(action) and tools.handle_command("0,0")
        view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
        editor.canvas.set_background_sketches((), view)
        assert tools.handle_command("5,7")
        assert services.kernel.drawing_datum_identifiers == (datum,)
        assert services.kernel.drawing_reference_dimensions == (reference,)
        assert "工作平面" in editor.canvas.message
    finally:
        QApplication.clipboard().clear()


@pytest.mark.parametrize("kind", ["frame", "datum"])
def test_rotated_annotation_display_and_selection(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, kind: Literal["frame", "datum"]
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), view)
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (15, 0))
    datum = DatumIdentifier(uuid4().hex, "A", (15, 0), (20, 0))
    if kind == "frame":
        tools.sync((frame,), ())
        expected = tools.screen_bounds(replace(frame, position_mm=(0, -15), rotation_deg=-90))
        identity = frame.frame_id
    else:
        tools.sync((), (datum,))
        expected = tools.datum_screen_bounds(
            replace(datum, position_mm=(0, -15), target_mm=(0, -20))
        )
        identity = datum.datum_id
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=expected.center().toPoint())
    assert tools.selected_id == identity
    canvas.set_background_sketches((), replace(WorkPlaneFrame.xy(), origin_mm=(0, 0, 1)))
    assert identity not in tools.selected_ids and tools.selected_id is None


@pytest.mark.parametrize("kind", ["frame", "datum"])
def test_rotated_annotation_position_grip_uses_drawing_coordinates(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, kind: Literal["frame", "datum"]
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 0))
    datum = DatumIdentifier(uuid4().hex, "A", (10, 0), (20, 0))
    source = frame if kind == "frame" else datum
    identity = frame.frame_id if kind == "frame" else datum.datum_id
    assert tools.execute is not None
    key = "add_frames" if kind == "frame" else "add_datums"
    assert tools.execute("drawing.tolerance.batch", {key: [source.to_mapping()]})
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    canvas = editor.canvas
    canvas.set_background_sketches((), view)
    canvas.set_tool("选择元素")
    tools.selected_id, tools.selected_kind, tools.selected_ids = identity, kind, {identity}
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, -10)))
    assert (tools.frame_grip if kind == "frame" else tools.datum_grip) is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 7)))
    result = (
        services.kernel.drawing_tolerance_frames[0]
        if kind == "frame"
        else services.kernel.drawing_datum_identifiers[0]
    )
    assert result.position_mm == pytest.approx((-7, 5))


@pytest.mark.parametrize("kind", ["frame", "datum"])
def test_rotated_annotation_clipboard_uses_drawing_coordinates(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, kind: Literal["frame", "datum"]
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QInputDialog
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)

    def datum_label(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "B", True

    monkeypatch.setattr(QInputDialog, "getText", datum_label)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (10, 0))
    datum = DatumIdentifier(uuid4().hex, "A", (10, 0), (20, 0))
    source = frame if kind == "frame" else datum
    identity = frame.frame_id if kind == "frame" else datum.datum_id
    assert tools.execute is not None
    key = "add_frames" if kind == "frame" else "add_datums"
    assert tools.execute("drawing.tolerance.batch", {key: [source.to_mapping()]})
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    canvas = editor.canvas
    canvas.set_background_sketches((), view)
    tools.selected_id, tools.selected_kind, tools.selected_ids = identity, kind, {identity}
    try:
        assert tools.copy_frame_to_clipboard() and tools.begin_frame_paste()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 7)))
        result = (
            services.kernel.drawing_tolerance_frames[-1]
            if kind == "frame"
            else services.kernel.drawing_datum_identifiers[-1]
        )
        assert result.position_mm == pytest.approx((-7, 5))
        if isinstance(result, DatumIdentifier):
            assert result.target_mm == pytest.approx((3, 5))
    finally:
        QApplication.clipboard().clear()


def test_rotated_simple_tolerance_placement_uses_drawing_coordinates(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.geometric_tolerance import ToleranceRow
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    canvas = editor.canvas
    canvas.set_background_sketches((), view)
    tools.pending_rows = (ToleranceRow("flatness", 0.1, 2),)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 7)))
    assert len(services.kernel.drawing_tolerance_frames) == 1
    assert services.kernel.drawing_tolerance_frames[0].position_mm == pytest.approx((-7, 5))


def test_rotated_datum_placement_attaches_to_reference_dimension(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    reference = DetachedDimension(uuid4().hex, "rotated", (10, 0), (20, 0), (15, 5), 0, 10)
    assert tools.execute is not None
    assert tools.execute("drawing.reference_dimensions.batch", {"add": [reference.to_mapping()]})
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    canvas = editor.canvas
    canvas.set_background_sketches((), view)
    tools.pending_datum_label = "A"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 7)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, -15)))
    assert len(services.kernel.drawing_datum_identifiers) == 1
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.position_mm == pytest.approx((-7, 5))
    assert datum.target_mm == pytest.approx((15, 5))
    assert datum.annotation_attachment is not None
    assert datum.annotation_attachment.object_id == reference.dimension_id


def test_rotated_datum_target_grip_reattaches_to_reference_dimension(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    first = DetachedDimension(uuid4().hex, "rotated", (10, 0), (20, 0), (15, 5), 0, 10)
    second = DetachedDimension(uuid4().hex, "rotated", (22, 0), (32, 0), (27, 5), 0, 10)
    assert tools.execute is not None
    assert tools.execute(
        "drawing.reference_dimensions.batch", {"add": [first.to_mapping(), second.to_mapping()]}
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (-5, 0),
        (15, 5),
        annotation_attachment=AnnotationAttachment(
            "reference_dimension", first.dimension_id, (0, 0)
        ),
    )
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    canvas = editor.canvas
    canvas.set_background_sketches((), view)
    canvas.set_tool("选择元素")
    tools.selected_id, tools.selected_kind, tools.selected_ids = (
        datum.datum_id,
        "datum",
        {datum.datum_id},
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, -15)))
    assert tools.datum_grip is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, -27)))
    changed = services.kernel.drawing_datum_identifiers[0]
    assert changed.target_mm == pytest.approx((27, 5))
    assert changed.annotation_attachment is not None
    assert changed.annotation_attachment.object_id == second.dimension_id


@pytest.mark.parametrize("reflected", [False, True])
def test_rotated_mechanical_frame_attaches_and_places_in_drawing_coordinates(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, reflected: bool
) -> None:
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.ui.geometric_tolerance_dialog import GeometricToleranceDialog
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    reference = DetachedDimension(uuid4().hex, "rotated", (10, 0), (20, 0), (15, 5), 0, 10)
    assert tools.execute is not None
    assert tools.execute("drawing.reference_dimensions.batch", {"add": [reference.to_mapping()]})
    view = (
        WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
        if reflected
        else WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    canvas = editor.canvas
    canvas.set_background_sketches((), view)
    tools.begin_mechanical_frame()
    target_in_view = view.world_to_local((15, 5, 0))
    destination = WorkPlaneFrame.xy().world_to_local(view.local_to_world((5, 7)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(target_in_view))
    assert tools.mechanical_frame_target == pytest.approx((15, 5))
    tools.mechanical_frame_cursor = destination
    points: list[tuple[float, float]] = []
    original_screen = canvas.local_to_screen

    def screen(point: tuple[float, float]) -> QPoint:
        points.append(point)
        return original_screen(point)

    monkeypatch.setattr(canvas, "local_to_screen", screen)
    image = QImage(600, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        tools.draw(painter)
    finally:
        painter.end()
    assert target_in_view in points and (5, 7) in points

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    assert tools.handle_command("5,7")
    result = services.kernel.drawing_tolerance_frames[0]
    assert result.position_mm == pytest.approx(destination)
    assert result.leader_target_mm == pytest.approx((15, 5))
    assert result.leader_annotation_attachment is not None
    assert result.leader_annotation_attachment.object_id == reference.dimension_id


@pytest.mark.parametrize("kind", ["frame", "datum"])
def test_mechanical_annotation_orthogonal_constraint_uses_canvas_axes(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, kind: Literal["frame", "datum"]
) -> None:
    import math

    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    c = math.sqrt(0.5)
    view = WorkPlaneFrame((0, 0, 0), (c, c, 0), (-c, c, 0), (0, 0, 1))
    canvas.set_background_sketches((), view)

    def unsnapped(point: tuple[float, float]) -> tuple[tuple[float, float], bool]:
        return point, False

    monkeypatch.setattr(canvas, "snap_annotation_point", unsnapped)
    tools.mechanical_leader_orthogonal = True
    if kind == "frame":
        tools.mechanical_frame_target = (0, 0)
        tools.mechanical_frame_vertices = [(0, 0)]
        name = "_constrain_frame_mouse"
    else:
        tools.mechanical_datum_target = (0, 0)
        tools.mechanical_datum_vertices = [(0, 0)]
        name = "_constrain_datum_mouse"
    result = cast("Callable[[tuple[float, float]], tuple[float, float]]", getattr(tools, name))(
        (10, 4)
    )
    assert result == pytest.approx((10 * c, 10 * c))


def test_rotated_mechanical_datum_preview_and_placement(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.main_window import MainWindow

    def datum_label(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    monkeypatch.setattr(QInputDialog, "getText", datum_label)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    canvas = editor.canvas
    canvas.set_background_sketches((), view)

    def unsnapped(point: tuple[float, float]) -> tuple[tuple[float, float], bool]:
        return point, False

    monkeypatch.setattr(canvas, "snap_annotation_point", unsnapped)
    tools.begin_mechanical_datum()
    assert tools.handle_command("N")
    canvas.pointer_moved.emit(canvas.local_to_screen((5, 7)))
    preview = tools.mechanical_datum_preview
    assert preview is not None and preview.position_mm == pytest.approx((-7, 5))
    projected = tools.display_datum(preview)
    assert projected is not None and projected.position_mm == pytest.approx((5, 7))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 7)))
    assert services.kernel.drawing_datum_identifiers[0].position_mm == pytest.approx((-7, 5))


@pytest.mark.parametrize("kind", ["frame", "datum"])
@pytest.mark.parametrize("reflected", [False, True])
def test_mechanical_auto_normal_on_coplanar_view(
    qtbot: object,
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["frame", "datum"],
    reflected: bool,
) -> None:
    from PySide6.QtWidgets import QDialog, QInputDialog
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame
    from mycad.core.sketch import Sketch
    from mycad.ui.geometric_tolerance_dialog import GeometricToleranceDialog
    from mycad.ui.main_window import MainWindow

    def datum_label(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    def accept(_dialog: GeometricToleranceDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    monkeypatch.setattr(QInputDialog, "getText", datum_label)
    monkeypatch.setattr(GeometricToleranceDialog, "exec", accept)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 20))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    view = (
        WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
        if reflected
        else WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    editor.canvas.set_background_sketches(services.kernel.sketches, view)
    if kind == "frame":
        tools.begin_mechanical_frame()
    else:
        tools.begin_mechanical_datum()
    assert tools.handle_command("0,0")
    destination = view.world_to_local((10, 15, 0))
    assert tools.handle_command(f"{destination[0]},{destination[1]}")
    item = (
        services.kernel.drawing_tolerance_frames[0]
        if kind == "frame"
        else services.kernel.drawing_datum_identifiers[0]
    )
    assert item.position_mm == pytest.approx((10, 15))
    attachment = (
        item.leader_attachment if isinstance(item, FeatureControlFrame) else item.attachment
    )
    assert attachment is not None and attachment.sketch_id == sketch.sketch_id
    assert item.leader_auto_normal and item.leader_offsets
    vertex = (
        item.position_mm[0] + item.leader_offsets[-1][0],
        item.position_mm[1] + item.leader_offsets[-1][1],
    )
    assert vertex[0] + vertex[1] == pytest.approx(0, abs=1e-8)


def test_rotated_datum_surface_edit_preview_matches_commit(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    tools = editor.canvas.geometric_tolerance_tools
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0))
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    canvas = editor.canvas
    canvas.set_background_sketches((), view)
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {datum.datum_id},
        datum.datum_id,
        "datum",
    )
    tools.begin_surface_indication_edit()
    canvas.pointer_moved.emit(canvas.local_to_screen((5, 7)))
    preview = tools.surface_edit_preview
    assert preview is not None and preview.surface_indication is not None
    assert preview.surface_indication.reference_start_offset_mm == pytest.approx((-7, 5))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 7)))
    result = services.kernel.drawing_datum_identifiers[0]
    assert result.surface_indication == preview.surface_indication


@pytest.mark.parametrize("mode", ["paste", "copy"])
def test_rotated_legacy_mixed_annotation_paste_reopens_atomically(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, tmp_path: object, mode: str
) -> None:
    from pathlib import Path

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QInputDialog
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    def datum_label(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "B", True

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    monkeypatch.setattr(QInputDialog, "getText", datum_label)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    reference = DetachedDimension(uuid4().hex, "aligned", (0, 0), (10, 0), (0, 5), 0, 10)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 5),
        annotation_attachment=AnnotationAttachment(
            "reference_dimension", reference.dimension_id, (0, 0)
        ),
    )
    assert tools.execute("drawing.reference_dimensions.batch", {"add": [reference.to_mapping()]})
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    tools.selected_ids = {reference.dimension_id, datum.datum_id}
    tools.selected_id, tools.selected_kind = datum.datum_id, "datum"
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    editor.canvas.set_background_sketches((), view)
    try:
        if mode == "paste":
            assert tools.copy_frame_to_clipboard() and tools.begin_frame_paste()
            QTest.mouseClick(
                editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 7))
            )
        else:
            assert tools.handle_command("COPY")
            assert tools.handle_command("0,0")
            assert tools.handle_command("5,7")
        copied_datum = services.kernel.drawing_datum_identifiers[-1]
        copied_reference = services.kernel.drawing_reference_dimensions[-1]
        expected_position = (-7, 5) if mode == "paste" else (13, 25)
        expected_target = (-27, -10) if mode == "paste" else (-7, 10)
        assert copied_datum.position_mm == pytest.approx(expected_position)
        assert copied_datum.target_mm == pytest.approx(expected_target)
        assert copied_reference.location_mm == pytest.approx(expected_target)
        assert copied_datum.annotation_attachment is not None
        assert copied_datum.annotation_attachment.object_id == copied_reference.dimension_id
        path = cast("Path", tmp_path) / "mixed-annotation.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        reopened.bus.undo_operation()
        assert services.kernel.drawing_datum_identifiers == (datum,)
        assert services.kernel.drawing_reference_dimensions == (reference,)
        reopened.bus.redo_operation()
        assert services.kernel.drawing_datum_identifiers[-1] == copied_datum
        assert services.kernel.drawing_reference_dimensions[-1] == copied_reference
    finally:
        QApplication.clipboard().clear()


@pytest.mark.parametrize("source_rotated", [False, True])
def test_rotated_legacy_mixed_geometry_picture_and_frame_reopens_atomically(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, tmp_path: object, source_rotated: bool
) -> None:
    from pathlib import Path

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, -10),
    )
    horizontal = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(line.entity_id, "geometry"),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint, horizontal))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (20, 10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    raster = replace(raster_from_clipboard_image(image, "0", None), origin_mm=(5, 5))
    loaded.bus.execute(
        "drawing.raster.batch",
        {"action": "add", "images": [raster.to_mapping(version=2)]},
        "local",
        version=2,
    )
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.selected_constraint_ids = {constraint.constraint_id}
    editor.canvas.selected_raster_ids = {raster.image_id}
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {frame.frame_id},
        frame.frame_id,
        "frame",
    )
    try:
        view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
        monkeypatch.setattr(editor, "current_frame", lambda: view)
        if source_rotated:
            editor.canvas.set_background_sketches(services.kernel.sketches, view)
        assert tools.copy_frame_to_clipboard()
        if not source_rotated:
            editor.canvas.set_background_sketches(services.kernel.sketches, view)
        assert tools.begin_frame_paste()
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 7))
        )
        copied_sketch = services.kernel.sketches[-1]
        copied_frame = services.kernel.drawing_tolerance_frames[-1]
        copied_raster = services.kernel.drawing_rasters[-1]
        assert isinstance(copied_sketch.entities[0], LineEntity)
        assert copied_sketch.entities[0].start_mm == pytest.approx((-27, -5))
        assert (
            copied_sketch.constraints[0].references[0].entity_id
            == copied_sketch.entities[0].entity_id
        )
        assert copied_sketch.constraints[0].position_mm == pytest.approx((-17, -15))
        assert {item.kind for item in copied_sketch.constraints} == {"length", "horizontal"}
        assert copied_frame.position_mm == pytest.approx((-7, 5))
        assert copied_raster.origin_mm == pytest.approx((-22, 0))
        path = cast("Path", tmp_path) / "mixed-geometry-picture-frame.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        reopened.bus.undo_operation()
        assert services.kernel.sketches == (sketch,)
        assert services.kernel.drawing_tolerance_frames == (frame,)
        assert services.kernel.drawing_rasters == (raster,)
        reopened.bus.redo_operation()
        assert services.kernel.sketches[-1] == copied_sketch
        assert services.kernel.drawing_tolerance_frames[-1] == copied_frame
        assert services.kernel.drawing_rasters[-1] == copied_raster
    finally:
        QApplication.clipboard().clear()


def test_legacy_mixed_copy_rejects_ambiguous_constraint_identity(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow
    from mycad.core.sketch import Sketch
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    constraint_id = uuid4().hex
    lines = (LineEntity(uuid4().hex, (0, 0), (10, 0)), LineEntity(uuid4().hex, (0, 20), (10, 20)))
    for line in lines:
        constraint = SketchConstraint(
            constraint_id,
            "length",
            (SketchGeometryReference(line.entity_id, "geometry"),),
            10,
            "mm",
            driving=False,
            position_mm=(5, -5),
        )
        sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint,))
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (20, 10))
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    editor.canvas.selected_entity_ids = {lines[0].entity_id}
    editor.canvas.selected_constraint_ids = {constraint_id}
    tools.selected_ids, tools.selected_id, tools.selected_kind = (
        {frame.frame_id},
        frame.frame_id,
        "frame",
    )
    try:
        assert not tools.copy_frame_to_clipboard()
        assert "身份不唯一" in editor.canvas.message
    finally:
        QApplication.clipboard().clear()


def test_surface_extension_uses_current_work_plane(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_surface_extension import (
        SurfaceExtensionSpec,
        surface_extension_geometry,
    )
    from mycad.core.sketch import Sketch
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    spec = SurfaceExtensionSpec("end", 5, 1, 2)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=spec,
    )
    geometry = surface_extension_geometry(
        line, spec.side, spec.distance_mm, spec.offset_mm, spec.overshoot_mm
    )
    path = tools.surface_screen_path(attachment, source_sketches=(sketch,))
    expected = tuple(
        canvas.local_to_screen_precise(frame.world_to_local(sketch.frame.local_to_world(point)))
        for point in (geometry.start_mm, geometry.end_mm)
    )
    assert path == expected
    canvas.set_background_sketches((), replace(WorkPlaneFrame.xy(), origin_mm=(0, 0, 1)))
    assert tools.surface_screen_path(attachment, source_sketches=(sketch,)) == ()


def test_legacy_geometry_paste_projects_into_rotated_plane(qtbot: object) -> None:
    from PySide6.QtCore import QMimeData
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import Sketch
    from mycad.ui.drawing_clipboard import DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    line = LineEntity(uuid4().hex, (20, 0), (22, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    mime = QMimeData()
    mime.setData(DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard(sketch))
    QApplication.clipboard().setMimeData(mime)
    try:
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point((5, 7), exact_point=True)
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
        assert canvas.entities[0].start_mm == pytest.approx((5, 7))
        assert canvas.entities[0].end_mm == pytest.approx((5, 5))
    finally:
        QApplication.clipboard().clear()


def test_rotated_geometry_copy_preserves_source_plane(qtbot: object) -> None:
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad.ui.drawing_clipboard import DRAWING_CLIPBOARD_MIME, decode_drawing_clipboard
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    line = LineEntity(uuid4().hex, (0, -20), (0, -22))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    try:
        assert canvas.copy_to_clipboard()
        mime = QApplication.clipboard().mimeData()
        assert mime is not None
        sketch = decode_drawing_clipboard(bytes(mime.data(DRAWING_CLIPBOARD_MIME).data()))
        assert sketch.frame == frame
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point((5, 7), exact_point=True)
        copied = canvas.entities[-1]
        assert isinstance(copied, LineEntity)
        assert copied.start_mm == pytest.approx((5, 7))
        assert copied.end_mm == pytest.approx((5, 5))
    finally:
        QApplication.clipboard().clear()


def test_legacy_constrained_paste_requires_collection_session(qtbot: object) -> None:
    from PySide6.QtCore import QMimeData
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import Sketch
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.drawing_clipboard import DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    line = LineEntity(uuid4().hex, (20, 0), (22, 0))
    relation = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(line.entity_id, "geometry"),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (relation,))
    mime = QMimeData()
    mime.setData(DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard(sketch))
    QApplication.clipboard().setMimeData(mime)
    try:
        assert not canvas.begin_clipboard_paste()
        assert "无法暂存" in canvas.message
        assert not canvas.entities and not canvas.constraints
    finally:
        QApplication.clipboard().clear()


@pytest.mark.parametrize("offset", [False, True])
def test_legacy_constrained_paste_rejects_non_coplanar_view_before_staging(
    qtbot: object, offset: bool
) -> None:
    from PySide6.QtCore import QMimeData
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import Sketch
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.drawing_clipboard import DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    frame = (
        WorkPlaneFrame((0, 0, 1), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
        if offset
        else WorkPlaneFrame.xz()
    )
    canvas.set_background_sketches((), frame)
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    constraint = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(line.entity_id, "geometry"),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint,))
    mime = QMimeData()
    mime.setData(DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard(sketch))
    QApplication.clipboard().setMimeData(mime)
    try:
        assert not canvas.begin_clipboard_paste()
        assert "共面" in canvas.message
        assert canvas.collection_session is None and not canvas.entities and not canvas.constraints
    finally:
        QApplication.clipboard().clear()


@pytest.mark.parametrize("existing_session", [False, True])
def test_legacy_constrained_paste_keeps_source_plane_in_collection_session(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, tmp_path: object, existing_session: bool
) -> None:
    from pathlib import Path

    from PySide6.QtCore import QMimeData, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
    from mycad.core.drawing_text import TextStyle
    from mycad.core.persistence import save_document
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch import Sketch
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.drawing_clipboard import DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard
    from mycad.ui.drawing_collection_session import DrawingCollectionSession
    from mycad.ui.main_window import MainWindow

    bot = cast("QtBot", qtbot)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    bot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    editor.canvas.set_background_sketches((), view)

    def current_session() -> DrawingCollectionSession | None:
        return editor.canvas.collection_session

    definition = BlockDefinition(
        uuid4().hex, "BeforePaste", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    if existing_session:
        assert editor.canvas.begin_collection_paste is not None
        assert editor.canvas.begin_collection_paste()
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local")
        )
    line = LineEntity(uuid4().hex, (20, 0), (22, 0))
    constraint = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(line.entity_id, "geometry"),)
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        2,
        "mm",
        driving=False,
        position_mm=(21, 3),
        style_name="Shared",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint, dimension))
    styles = DimensionStyleTable(
        (DimensionStyle("Shared", text_height=5, text_style_id="standard"),), "Shared"
    )
    fonts = TextStyleTable((TextStyle(height_mm=7),), "standard")
    mime = QMimeData()
    mime.setData(DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard(sketch, styles, fonts))
    QApplication.clipboard().setMimeData(mime)
    try:
        assert editor.canvas.begin_clipboard_paste()
        QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
        prior = current_session()
        if existing_session:
            assert prior is not None and prior.snapshot.block_definitions == (definition,)
        else:
            assert prior is None
        assert not loaded.document.commands
        assert editor.canvas.begin_clipboard_paste()
        monkeypatch.setattr(editor.canvas, "_cursor", (5.0, 7.0))
        editor.canvas.grab()
        preview = editor.canvas.collection_paste_preview
        assert preview is not None and len(preview.payload.sketches) == 1
        editor.canvas.add_coordinate_point((5, 7), exact_point=True)
        session = current_session()
        assert session is not None and not loaded.document.commands
        pasted = next(item for item in session.snapshot.sketches if item.entities)
        assert pasted.frame == sketch.frame
        copied = pasted.entities[0]
        assert isinstance(copied, LineEntity)
        assert copied.start_mm == pytest.approx((-7, 5))
        assert copied.end_mm == pytest.approx((-5, 5))
        assert pasted.constraints[0].kind == "horizontal"
        assert pasted.constraints[0].references[0].entity_id == copied.entity_id
        assert pasted.constraints[1].position_mm == pytest.approx((-6, 8))
        assert pasted.constraints[1].references[0].entity_id == copied.entity_id
        pasted_style = session.snapshot.dimension_styles.get(
            cast("str", pasted.constraints[1].style_name)
        )
        assert pasted_style.text_height == 5
        assert (
            session.snapshot.text_styles.get(cast("str", pasted_style.text_style_id)).height_mm == 7
        )
        assert preview.payload.sketches[0].entities == pasted.entities
        assert preview.payload.sketches[0].constraints == (pasted.constraints[1],)
        assert editor.canvas.undo_last_operation()
        assert not any(item.entities for item in session.snapshot.sketches)
        assert editor.canvas.redo_last_operation()
        editor.finish_sketch()
        bot.waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
        )
        path = cast("Path", tmp_path) / "legacy-constrained.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert services.kernel.sketches == (pasted,)
        reopened.bus.undo_operation()
        assert services.kernel.sketches == ()
        assert services.kernel.drawing_block_definitions == (
            (definition,) if existing_session else ()
        )
        reopened.bus.redo_operation()
        assert services.kernel.sketches == (pasted,)
    finally:
        QApplication.clipboard().clear()


def test_rotated_work_plane_copies_mixed_geometry_and_picture(qtbot: object) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.sketch import Sketch
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    line = LineEntity(uuid4().hex, (0, -20), (0, -22))
    assert canvas.replace_draft_entities((line,))
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    raster = replace(raster_from_clipboard_image(image, "0", None), origin_mm=(20, 0))
    canvas.set_drawing_rasters((raster,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {raster.image_id}
    committed: list[tuple[Sketch, tuple[DrawingRaster, ...]]] = []
    canvas.commit_mixed_clipboard = lambda data, images, _styles, _fonts: committed.append(
        (data, images)
    )
    try:
        assert canvas.copy_to_clipboard() and canvas.begin_clipboard_paste()
        canvas.add_coordinate_point((5, 7), exact_point=True)
        assert len(committed) == 1
        placed, images = committed[0]
        assert placed.frame == frame
        assert isinstance(placed.entities[0], LineEntity)
        assert placed.entities[0].start_mm == pytest.approx((5, 7))
        assert images[0].origin_mm == pytest.approx((-7, 5))
    finally:
        QApplication.clipboard().clear()


def test_rotated_picture_block_group_clipboard_preview_matches_committed_display(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image
    from mycad.ui.main_window import MainWindow
    from mycad.ui.sketch_editor import SketchCanvas

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (30, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    raster = replace(
        raster_from_clipboard_image(image, "0", None), origin_mm=(20, 0), width_mm=10, height_mm=5
    )
    loaded.bus.execute(
        "drawing.raster.batch",
        {"action": "add", "images": [raster.to_mapping(version=2)]},
        "local",
        version=2,
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("raster", raster.image_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: frame)
    editor.canvas.set_background_sketches(services.kernel.sketches, frame)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    drawn: list[DrawingRaster] = []
    original = cast("Callable[..., None]", vars(SketchCanvas)["_draw_raster"])

    def record(
        target: SketchCanvas, painter: QPainter, item: DrawingRaster, **kwargs: object
    ) -> None:
        drawn.append(item)
        original(target, painter, item, **kwargs)

    monkeypatch.setattr(SketchCanvas, "_draw_raster", record)
    try:
        assert editor.canvas.copy_to_clipboard() and editor.canvas.begin_clipboard_paste()
        monkeypatch.setattr(editor.canvas, "_cursor", (5.0, 7.0))
        editor.canvas.grab()
        preview = editor.canvas.collection_paste_preview
        assert preview is not None and len(preview.payload.rasters) == 1
        copied_id = preview.payload.rasters[0].image_id
        preview_image = next(item for item in reversed(drawn) if item.image_id == copied_id)
        assert preview_image.origin_mm == pytest.approx((5, 7))
        assert preview_image.angle_deg == pytest.approx(-90)
        editor.canvas.add_coordinate_point((5, 7), exact_point=True)
        session = editor.canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 2
        copied = next(item for item in session.snapshot.rasters if item.image_id == copied_id)
        assert copied.origin_mm == pytest.approx((-7, 5))
        drawn.clear()
        editor.canvas.grab()
        displayed = next(item for item in reversed(drawn) if item.image_id == copied_id)
        assert displayed.origin_mm == pytest.approx(preview_image.origin_mm)
        assert displayed.angle_deg == pytest.approx(preview_image.angle_deg)
        assert editor.canvas.undo_last_operation() and session.snapshot.groups == (group,)
        editor.canvas.selected_block_instance_ids = {instance.instance_id}
        editor.canvas.begin_transform("move")
        editor.canvas.add_coordinate_point((0, 0), exact_point=True)
        monkeypatch.setattr(editor.canvas, "_cursor", (0.0, 2.0))
        transform = cast("Callable[..., None]", getattr(type(editor.canvas), _TRANSFORM_METHOD))
        transform(editor.canvas, (0.0, 2.0), commit=False)
        drawn.clear()
        editor.canvas.grab()
        moved_preview = next(item for item in reversed(drawn) if item.image_id == raster.image_id)
        assert moved_preview.origin_mm == pytest.approx((0, -18))
        editor.canvas.add_coordinate_point((0, 2), exact_point=True)
        assert session.snapshot.rasters[0].origin_mm == pytest.approx((18, 0))
        assert session.snapshot.block_instances[0].insertion_mm == pytest.approx((28, 0))
        drawn.clear()
        editor.canvas.grab()
        moved_display = next(item for item in reversed(drawn) if item.image_id == raster.image_id)
        assert moved_display.origin_mm == pytest.approx(moved_preview.origin_mm)
        assert editor.canvas.undo_last_operation() and session.snapshot.rasters == (raster,)
    finally:
        QApplication.clipboard().clear()


def test_fit_view_resolves_each_dimension_in_its_source_sketch(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QRectF
    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import Sketch, SketchEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = replace(first, start_mm=(100, 0), end_mm=(110, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 80),
    )
    other_dimension = replace(dimension, position_mm=(105, 80))
    canvas.set_background_sketches(
        (
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,), (dimension,)),
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second,), (other_dimension,)),
        ),
        WorkPlaneFrame.xy(),
    )
    actual: list[tuple[SketchConstraint, SketchEntity]] = []
    original = canvas.dimension_layout

    def record(constraint: SketchConstraint, entities: dict[str, SketchEntity]) -> object:
        actual.append((constraint, entities[constraint.references[0].entity_id]))
        return original(constraint, entities)

    monkeypatch.setattr(canvas, "dimension_layout", record)
    canvas.fit_view()
    assert actual == [(dimension, first), (other_dimension, second)]
    viewport = QRectF(canvas.rect())
    for constraint, entity in ((dimension, first), (other_dimension, second)):
        layout = original(constraint, {entity.entity_id: entity})
        assert layout is not None
        assert viewport.contains(layout.label)
        assert all(viewport.contains(point) for segment in layout.lines for point in segment)


def test_fit_view_draws_block_far_from_drawing_origin(qtbot: object) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    line = LineEntity(uuid4().hex, (0, 0), (1e6, 0))
    definition = BlockDefinition(uuid4().hex, "Far", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (1e20, 1e20))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    canvas.fit_view()
    canvas.show()
    image = canvas.grab().toImage()
    first = canvas.local_to_screen((1e20, 1e20))
    last = canvas.local_to_screen((1e20 + 1e6, 1e20))
    assert canvas.rect().contains(first) and canvas.rect().contains(last)
    assert any(
        image.pixelColor(x, y).lightness() < 100
        for x in range(min(first.x(), last.x()), max(first.x(), last.x()) + 1)
        for y in range(max(0, first.y() - 2), min(canvas.height(), first.y() + 3))
    )
    assert canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        pos=QPoint((first.x() + last.x()) // 2, first.y()),
    )
    assert canvas.selected_block_instance_ids == {instance.instance_id}


@pytest.mark.parametrize("extent", [1e20, 1e200])
def test_fit_view_includes_extremely_large_block_and_can_zoom(qtbot: object, extent: float) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    line = LineEntity(uuid4().hex, (0, 0), (extent, 0))
    definition = BlockDefinition(uuid4().hex, "Large", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    canvas.fit_view()
    assert canvas.rect().contains(canvas.local_to_screen((0, 0)))
    assert canvas.rect().contains(canvas.local_to_screen((extent, 0)))
    before = canvas.view_scale
    canvas.zoom_view_factor(2)
    assert canvas.view_scale == pytest.approx(before * 2, abs=0)
    canvas.show()
    previous = canvas.view_scale
    position = QPointF(canvas.rect().center())
    QApplication.sendEvent(
        canvas,
        QWheelEvent(
            position,
            position,
            QPoint(),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        ),
    )
    assert canvas.view_scale == pytest.approx(previous * 1.15, abs=0)
    canvas.grab()
    assert canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((extent / 2, 0)))
    assert canvas.selected_block_instance_ids == {instance.instance_id}
    hit = cast("Callable[[Point2D], str | None]", getattr(canvas, _BLOCK_HIT_METHOD))
    assert hit((extent / 2, extent / 10)) is None
    candidates = cast("Callable[[], list[tuple[Point2D, str]]]", getattr(canvas, _SNAP_METHOD))()
    assert ((extent / 2, 0), "中点") in candidates
    assert canvas.selectable_entities() == ()


def test_block_edges_contribute_coordinate_only_intersection_snaps(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    horizontal = LineEntity(uuid4().hex, (0, 0), (10, 0))
    vertical = LineEntity(uuid4().hex, (0, -2), (0, 2))
    first_definition = BlockDefinition(uuid4().hex, "Horizontal", (horizontal,), ())
    second_definition = BlockDefinition(uuid4().hex, "Vertical", (vertical,), ())
    first = BlockInstance(uuid4().hex, first_definition.definition_id, (0, 0), layer_name="B")
    second = BlockInstance(uuid4().hex, second_definition.definition_id, (7, 0))
    canvas.set_layer_table(SketchLayerTable().add(SketchLayer("B")), "0")
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (2, -2), (2, 2)),))
    canvas.set_drawing_blocks(
        (first_definition, second_definition), (first, second), TextStyleTable()
    )
    candidates = cast("Callable[[], list[tuple[Point2D, str]]]", getattr(canvas, _SNAP_METHOD))
    assert ((2, 0), "交点") in candidates()
    assert ((7, 0), "交点") in candidates()
    assert all(
        item.entity not in canvas.selectable_entities()
        for item in canvas.drawing_block_view().geometry
    )
    layers = canvas.layer_table.replace(replace(canvas.layer_table.get("B"), visible=False))
    canvas.set_layer_table(layers, "0")
    assert ((2, 0), "交点") not in candidates()
    assert ((7, 0), "交点") not in candidates()


def test_extremely_large_block_edges_offer_intersection_and_perpendicular_snaps(
    qtbot: object,
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    horizontal = LineEntity(uuid4().hex, (0, 0), (1e200, 0))
    vertical = LineEntity(uuid4().hex, (5e199, -1e200), (5e199, 1e200))
    separate = LineEntity(uuid4().hex, (0, 2e200), (1e200, 2e200))
    definition = BlockDefinition(uuid4().hex, "Large", (horizontal, vertical, separate), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    candidates = cast("Callable[[], list[tuple[Point2D, str]]]", getattr(canvas, _SNAP_METHOD))()
    assert [point for point, kind in candidates if kind == "交点"] == [(5e199, 0)]
    reference = cast(
        "Callable[[Point2D], list[tuple[Point2D, str]]]", getattr(canvas, _REFERENCE_SNAP_METHOD)
    )((5e199, 1e199))
    assert ((5e199, 0), "垂足") in reference
    assert canvas.selectable_entities() == ()


def test_large_block_circle_center_tangency_stays_finite(qtbot: object) -> None:
    import math

    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import CircleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    radius = 1e200
    circle = CircleEntity(uuid4().hex, (0, 0), radius)
    definition = BlockDefinition(uuid4().hex, "Large", (circle,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    setattr(canvas, _FIRST_POINT_FIELD, (2e200, 0))
    candidates = cast(
        "Callable[[], list[tuple[Point2D, str]]]", getattr(canvas, _CENTER_TANGENT_SNAP_METHOD)
    )()
    points = [point for point, kind in candidates if kind == "切点"]
    assert len(points) == 2 and all(math.isfinite(value) for point in points for value in point)
    assert any(point == pytest.approx((radius, 0), rel=1e-12, abs=0) for point in points)
    assert any(point == pytest.approx((-radius, 0), rel=1e-12, abs=0) for point in points)
    assert canvas.selectable_entities() == ()


def test_large_block_line_center_tangency_stays_finite(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    line = LineEntity(uuid4().hex, (-1e200, 0), (1e200, 0))
    definition = BlockDefinition(uuid4().hex, "Large", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    setattr(canvas, _FIRST_POINT_FIELD, (0, 1e200))
    candidates = cast(
        "Callable[[], list[tuple[Point2D, str]]]", getattr(canvas, _CENTER_TANGENT_SNAP_METHOD)
    )()
    assert ((0, 0), "切点") in candidates
    assert canvas.selectable_entities() == ()


def test_extreme_block_circle_center_tangency_handles_overflowed_difference(qtbot: object) -> None:
    import math

    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import CircleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    circle = CircleEntity(uuid4().hex, (1e308, 0), 1e307)
    definition = BlockDefinition(uuid4().hex, "Extreme", (circle,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    setattr(canvas, _FIRST_POINT_FIELD, (-1e308, 0))
    candidates = cast(
        "Callable[[], list[tuple[Point2D, str]]]", getattr(canvas, _CENTER_TANGENT_SNAP_METHOD)
    )()
    points = [point for point, kind in candidates if kind == "切点"]
    assert len(points) == 2 and all(math.isfinite(value) for point in points for value in point)
    assert any(point == pytest.approx((9e307, 0), rel=1e-12, abs=0) for point in points)
    assert any(point == pytest.approx((1.1e308, 0), rel=1e-12, abs=0) for point in points)


def test_extreme_block_circle_external_tangencies_keep_distance_ratio(qtbot: object) -> None:
    import math

    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import CircleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    circle = CircleEntity(uuid4().hex, (1e308, 0), 1e307)
    definition = BlockDefinition(uuid4().hex, "Extreme", (circle,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    candidates = cast(
        "Callable[[Point2D], list[tuple[Point2D, str]]]", getattr(canvas, _REFERENCE_SNAP_METHOD)
    )((-1e308, 0))
    points = [point for point, kind in candidates if kind == "切点"]
    expected_y = 1e307 * math.sqrt(1 - 0.05**2)
    assert len(points) == 2
    assert any(point == pytest.approx((9.95e307, expected_y), rel=1e-12, abs=0) for point in points)
    assert any(
        point == pytest.approx((9.95e307, -expected_y), rel=1e-12, abs=0) for point in points
    )


def test_large_block_circle_intersections_are_coordinate_only(qtbot: object) -> None:
    import math

    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import CircleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    radius = 1e200
    line = LineEntity(uuid4().hex, (-2e200, 0), (2e200, 0))
    first = CircleEntity(uuid4().hex, (0, 0), radius)
    second = CircleEntity(uuid4().hex, (radius, 0), radius)
    definition = BlockDefinition(uuid4().hex, "Large", (line, first, second), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    candidates = cast("Callable[[], list[tuple[Point2D, str]]]", getattr(canvas, _SNAP_METHOD))()
    intersections = [point for point, kind in candidates if kind == "交点"]
    for expected in (
        (-radius, 0),
        (radius, 0),
        (0, 0),
        (2 * radius, 0),
        (radius / 2, radius * math.sqrt(3) / 2),
        (radius / 2, -radius * math.sqrt(3) / 2),
    ):
        assert any(point == pytest.approx(expected, rel=1e-12, abs=0) for point in intersections)
    assert canvas.selectable_entities() == ()


@pytest.mark.parametrize("height", [1, 2])
def test_large_block_line_circle_tangent_or_disjoint(qtbot: object, height: int) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import CircleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    radius = 1e200
    line = LineEntity(uuid4().hex, (-radius, height * radius), (radius, height * radius))
    circle = CircleEntity(uuid4().hex, (0, 0), radius)
    definition = BlockDefinition(uuid4().hex, "Large", (line, circle), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    candidates = cast("Callable[[], list[tuple[Point2D, str]]]", getattr(canvas, _SNAP_METHOD))()
    intersections = [point for point, kind in candidates if kind == "交点"]
    assert intersections == ([(0, radius)] if height == 1 else [])


def test_block_circle_contributes_coordinate_only_tangent_snaps(qtbot: object) -> None:
    import math

    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import CircleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    definition = BlockDefinition(uuid4().hex, "Circle", (circle,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    candidates = cast(
        "Callable[[Point2D], list[tuple[Point2D, str]]]",
        getattr(canvas, _REFERENCE_SNAP_METHOD),
    )((10, 0))
    tangencies = [point for point, kind in candidates if kind == "切点"]
    assert len(tangencies) == 2
    assert all(point[0] == pytest.approx(2.5) for point in tangencies)
    assert canvas.drawing_block_view().geometry[0].entity not in canvas.selectable_entities()
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((2.5, 4.33))
    assert canvas.current_snap_kind == "切点"
    assert isinstance(canvas.entities[-1], LineEntity)
    assert canvas.entities[-1].end_mm == pytest.approx((2.5, 5 * math.sqrt(3) / 2))
    assert canvas.constraints == []


def test_committed_block_view_refreshes_after_update_and_undo(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    second = BlockInstance(uuid4().hex, definition.definition_id, (10, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", second.to_mapping(), "local")
    sync = cast("Callable[[], None]", getattr(window, _SYNC_METHOD))
    sync()
    initial = editor.canvas.drawing_block_view().geometry[0].entity
    assert isinstance(initial, LineEntity) and initial.end_mm == (2, 0)
    other = editor.canvas.drawing_block_view().geometry[1].entity
    assert isinstance(other, LineEntity) and other.end_mm == (12, 0)
    updated = replace(definition, entities=(replace(line, end_mm=(4, 0)),))
    loaded.bus.execute("drawing.block.update", updated.to_mapping(), "local")
    sync()
    revised = editor.canvas.drawing_block_view().geometry[0].entity
    assert isinstance(revised, LineEntity) and revised.end_mm == (4, 0)
    other_revised = editor.canvas.drawing_block_view().geometry[1].entity
    assert isinstance(other_revised, LineEntity) and other_revised.end_mm == (14, 0)
    loaded.bus.undo_operation()
    sync()
    assert editor.canvas.drawing_block_view().geometry[0].entity == initial
    assert editor.canvas.drawing_block_view().geometry[1].entity == other


def test_click_block_instance_then_move_and_undo(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.drawing_collection_session import DrawingCollectionTransformPreview
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    first = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    second = BlockInstance(uuid4().hex, definition.definition_id, (25, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", first.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", second.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((12, 10))
    )
    assert editor.canvas.selected_block_instance_ids == {first.instance_id}
    assert editor.canvas.selected_entity_ids == set()
    editor.canvas.begin_transform("move")
    assert editor.canvas.collection_session is not None
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    preview_point = (0, 5)
    transform = cast("Callable[..., None]", getattr(editor.canvas, _TRANSFORM_METHOD))
    transform(preview_point, commit=False)
    preview = getattr(editor.canvas, _PREVIEW_FIELD)
    assert isinstance(preview, DrawingCollectionTransformPreview)
    assert len(preview.payload.sketches) == 1
    preview_id = preview.payload.sketches[0].entities[0].entity_id
    editor.canvas.add_coordinate_point((0, 5), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None
    assert session.snapshot.block_instances == (replace(first, insertion_mm=(10, 15)), second)
    assert editor.canvas.drawing_block_view().geometry[0].entity.entity_id == preview_id
    assert services.kernel.drawing_block_instances == (first, second)
    editor.canvas.cancel_transform()
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.block_instances == (first, second)
    assert editor.canvas.selected_block_instance_ids == {first.instance_id}


@pytest.mark.parametrize("action", ["copy", "rotate", "scale", "delete"])
def test_selected_block_instance_transforms_and_undoes(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.drawing_collection_session import DrawingCollectionTransformPreview
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((12, 10))
    )
    assert editor.canvas.selected_block_instance_ids == {instance.instance_id}
    preview_id: str | None = None
    if action == "delete":
        assert editor.canvas.delete_selected()
    else:
        editor.canvas.begin_transform(action)
        editor.canvas.add_coordinate_point((0, 0), exact_point=True)
        if action == "copy":
            cast("Callable[..., None]", getattr(editor.canvas, _TRANSFORM_METHOD))(
                (0, 5), commit=False
            )
            preview = getattr(editor.canvas, _PREVIEW_FIELD)
            assert isinstance(preview, DrawingCollectionTransformPreview)
            preview_id = preview.payload.sketches[0].entities[0].entity_id
            editor.canvas.add_coordinate_point((0, 5), exact_point=True)
            editor.canvas.cancel_transform()
        elif action == "rotate":
            assert editor.canvas.apply_rotation_angle(90)
        else:
            assert editor.canvas.apply_scale_factor(2)
    session = editor.canvas.collection_session
    assert session is not None
    values = session.snapshot.block_instances
    if action == "copy":
        assert len(values) == 2 and values[1].insertion_mm == (10, 15)
        assert preview_id == editor.canvas.drawing_block_view().geometry[1].entity.entity_id
    elif action == "delete":
        assert values == () and session.snapshot.block_definitions == (definition,)
    elif action == "rotate":
        assert values[0].insertion_mm == pytest.approx((-10, 10)) and values[0].rotation_deg == 90
    else:
        assert values[0].insertion_mm == (20, 20) and values[0].scale == 2
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.block_instances == (instance,)
    assert editor.canvas.selected_block_instance_ids == {instance.instance_id}


@pytest.mark.parametrize("action", ["scale", "rotate"])
def test_small_block_transform_is_staged_from_canvas(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((12, 10))
    )
    assert editor.canvas.selected_block_instance_ids == {instance.instance_id}
    editor.canvas.begin_transform(action)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    if action == "scale":
        assert editor.canvas.apply_scale_factor(1 + 1e-11)
    else:
        assert editor.canvas.apply_rotation_angle(1e-11)
    session = editor.canvas.collection_session
    assert session is not None
    transformed = session.snapshot.block_instances[0]
    assert transformed != instance
    assert transformed.scale == (1 + 1e-11 if action == "scale" else 1)
    assert transformed.rotation_deg == (1e-11 if action == "rotate" else 0)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.block_instances == (instance,)


@pytest.mark.parametrize("action", ["scale", "rotate"])
@pytest.mark.parametrize("commit_mode", ["numeric", "point"])
def test_group_affine_copy_is_one_staged_operation_with_frozen_preview(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, tmp_path: object, action: str, commit_mode: str
) -> None:
    from pathlib import Path

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.persistence import save_document
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image
    from mycad.ui.drawing_collection_session import DrawingCollectionAffinePreview
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.group_button.click()
    session = editor.canvas.collection_session
    assert session is not None
    original_group = session.snapshot.groups[0]
    text = DrawingText(uuid4().hex, "T", (3, 0), height_mm=2)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local")
    )
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    raster = replace(
        raster_from_clipboard_image(image, "0", None),
        origin_mm=(5, 0),
        width_mm=4,
        height_mm=2,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [raster.to_mapping(version=2)]},
            "local",
        )
    )
    group = replace(
        original_group,
        members=(
            *original_group.members,
            DrawingObjectRef("text", text.text_id),
            DrawingObjectRef("raster", raster.image_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.update", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform(action)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    if action == "scale":
        assert editor.canvas.enable_scale_copy()
        target, value = (2.0, 0.0), 2.0
    else:
        assert editor.canvas.enable_rotation_copy()
        target, value = (0.0, 1.0), 90.0
    transform = cast("Callable[..., None]", getattr(type(editor.canvas), _TRANSFORM_METHOD))
    transform(editor.canvas, target, commit=False)
    preview = cast("DrawingCollectionAffinePreview | None", getattr(editor.canvas, _PREVIEW_FIELD))
    assert preview is not None and session.snapshot == before
    preview_ids = {
        entity.entity_id for sketch in preview.payload.sketches for entity in sketch.entities
    }
    assert preview_ids
    if commit_mode == "point":
        transform(editor.canvas, target, commit=True)
    elif action == "scale":
        assert editor.canvas.apply_scale_factor(value)
    else:
        assert editor.canvas.apply_rotation_angle(value)
    after = session.snapshot
    assert len(after.groups) == 2 and after.groups[0] == group
    copied_group = after.groups[1]
    preview_operations = cast("list[dict[str, object]]", preview.operation.params["operations"])
    preview_group = next(
        item for item in preview_operations if item["id"] == "drawing.group.create"
    )
    assert copied_group == DrawingGroup.from_mapping(preview_group["params"])
    copied_geometry = next(ref for ref in copied_group.members if ref.kind == "geometry")
    copied_text = next(ref for ref in copied_group.members if ref.kind == "text")
    copied_raster = next(ref for ref in copied_group.members if ref.kind == "raster")
    copied_block = next(ref for ref in copied_group.members if ref.kind == "block_instance")
    assert copied_geometry.object_id in preview_ids
    copied_line = next(
        entity
        for sketch in after.sketches
        for entity in sketch.entities
        if sketch.sketch_id == copied_geometry.sketch_id
        and entity.entity_id == copied_geometry.object_id
    )
    assert isinstance(copied_line, LineEntity)
    expected = (2, 0) if action == "scale" else (0, 1)
    assert copied_line.start_mm == pytest.approx(expected)
    assert next(
        item for item in after.texts if item.text_id == copied_text.object_id
    ).position_mm == pytest.approx((6, 0) if action == "scale" else (0, 3))
    copied_instance = next(
        item for item in after.block_instances if item.instance_id == copied_block.object_id
    )
    assert copied_instance.definition_id == definition.definition_id
    assert copied_instance.insertion_mm == pytest.approx((8, 0) if action == "scale" else (0, 4))
    copied_picture = next(
        item for item in after.rasters if item.image_id == copied_raster.object_id
    )
    assert copied_picture.origin_mm == pytest.approx((10, 0) if action == "scale" else (0, 5))
    assert copied_picture.width_mm == (8 if action == "scale" else 4)
    assert copied_picture.angle_deg == (0 if action == "scale" else 90)
    assert after.rasters[0] == raster
    assert after.block_instances[0] == instance
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = cast("Path", tmp_path) / "affine-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after
    if commit_mode == "numeric":
        target_sketch = next(
            sketch
            for sketch in services.kernel.sketches
            if sketch.sketch_id == copied_geometry.sketch_id
        )
        extra = LineEntity(uuid4().hex, (40, 40), (42, 40))
        extended = replace(target_sketch, entities=(*target_sketch.entities, extra))
        state = extended.to_state_mapping()
        reopened.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": target_sketch.sketch_id,
                        "base_state_sha256": target_sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
            version=79,
        )
        revised = app.drawing_collection_snapshot(services)
        assert revised.groups == after.groups and revised.block_instances == after.block_instances
        assert revised.texts == after.texts and revised.rasters == after.rasters
        revised_path = cast("Path", tmp_path) / "affine-copy-revised.my2d"
        save_document(reopened.document, revised_path)
        revised_document = app.open_app_document(services, revised_path)
        assert app.drawing_collection_snapshot(services) == revised
        revised_document.bus.undo_operation()
        assert app.drawing_collection_snapshot(services) == after
        revised_document.bus.undo_operation()
        assert app.drawing_collection_snapshot(services) == before
        revised_document.bus.redo_operation()
        revised_document.bus.redo_operation()
        assert app.drawing_collection_snapshot(services) == revised


@pytest.mark.parametrize(("action", "value"), [("scale", 1.0), ("rotate", 0.0)])
def test_group_affine_copy_with_identity_transform_still_copies(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, action: str, value: float
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.group_button.click()
    session = editor.canvas.collection_session
    assert session is not None
    before = session.snapshot
    editor.canvas.begin_transform(action)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    if action == "scale":
        assert editor.canvas.enable_scale_copy()
        assert editor.canvas.apply_scale_factor(value)
    else:
        assert editor.canvas.enable_rotation_copy()
        assert editor.canvas.apply_rotation_angle(value)
    assert len(session.snapshot.groups) == 2
    assert editor.canvas.undo_last_operation() and session.snapshot == before


@pytest.mark.parametrize(("command", "value"), [("SCALE", "2"), ("ROTATE", "90")])
def test_group_affine_copy_from_command_bar(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, command: str, value: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.group_button.click()
    session = editor.canvas.collection_session
    assert session is not None
    before = session.snapshot
    editor.canvas.selected_entity_ids = {line.entity_id}
    for entry in (command, "0,0", "COPY", value):
        editor.drawing_command_bar.input.setText(entry)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert len(session.snapshot.groups) == 2
    assert editor.canvas.undo_last_operation() and session.snapshot == before


@pytest.mark.parametrize("action", ["scale", "rotate"])
def test_group_affine_copy_rejects_unsupported_member_without_partial_state(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_groups import DrawingObjectRef
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.group_button.click()
    session = editor.canvas.collection_session
    assert session is not None
    dimension = DetachedDimension(uuid4().hex, "aligned", (0, 2), (2, 2), (1, 3), 0, 2)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend(
            "drawing.reference_dimensions.batch", 10, {"add": [dimension.to_mapping()]}, "local"
        )
    )
    group = session.snapshot.groups[0]
    group = replace(
        group,
        members=(*group.members, DrawingObjectRef("reference_dimension", dimension.dimension_id)),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.update", 1, group.to_mapping(), "local")
    )
    before, checkpoint, history = (
        session.snapshot,
        session.checkpoint(),
        tuple(loaded.document.commands),
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform(action)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    if action == "scale":
        assert editor.canvas.enable_scale_copy()
        assert editor.canvas.apply_scale_factor(2)
    else:
        assert editor.canvas.enable_rotation_copy()
        assert editor.canvas.apply_rotation_angle(90)
    assert session.snapshot == before and session.checkpoint() == checkpoint
    assert tuple(loaded.document.commands) == history
    assert "不支持" in editor.status_label.text()


@pytest.mark.parametrize("action", ["scale", "rotate"])
def test_affine_copy_of_one_member_does_not_join_unselectable_group(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    first = LineEntity(uuid4().hex, (1, 0), (2, 0))
    second = LineEntity(uuid4().hex, (3, 0), (4, 0))
    assert editor.canvas.replace_draft_entities((first, second))
    editor.canvas.selected_entity_ids = {first.entity_id, second.entity_id}
    editor.group_button.click()
    session = editor.canvas.collection_session
    assert session is not None
    group = replace(session.snapshot.groups[0], selectable=False)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.update", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    editor.canvas.selected_entity_ids = {first.entity_id}
    editor.canvas.begin_transform(action)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    if action == "scale":
        assert editor.canvas.enable_scale_copy() and editor.canvas.apply_scale_factor(2)
    else:
        assert editor.canvas.enable_rotation_copy() and editor.canvas.apply_rotation_angle(90)
    after = session.snapshot
    assert after.groups == (group,)
    copied = tuple(
        item for sketch in after.sketches for item in sketch.entities if item not in (first, second)
    )
    assert len(copied) == 1 and isinstance(copied[0], LineEntity)
    assert copied[0].start_mm == pytest.approx((2, 0) if action == "scale" else (0, 1))
    assert editor.canvas.undo_last_operation() and session.snapshot == before


@pytest.mark.parametrize("action", ["scale", "rotate"])
def test_group_affine_copy_rebuilds_stale_preview_and_preserves_new_step(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.drawing_collection_session import DrawingCollectionAffinePreview
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.group_button.click()
    session = editor.canvas.collection_session
    assert session is not None
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform(action)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    if action == "scale":
        assert editor.canvas.enable_scale_copy()
        target, value = (2.0, 0.0), 2.0
    else:
        assert editor.canvas.enable_rotation_copy()
        target, value = (0.0, 1.0), 90.0
    transform = cast("Callable[..., None]", getattr(type(editor.canvas), _TRANSFORM_METHOD))
    transform(editor.canvas, target, commit=False)
    preview = cast("DrawingCollectionAffinePreview | None", getattr(editor.canvas, _PREVIEW_FIELD))
    assert preview is not None
    operations = cast("list[dict[str, object]]", preview.operation.params["operations"])
    old_group = DrawingGroup.from_mapping(
        next(item["params"] for item in operations if item["id"] == "drawing.group.create")
    )
    renamed = replace(session.snapshot.groups[0], name="Edited while previewing")
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.update", 1, renamed.to_mapping(), "local")
    )
    before, history = session.snapshot, tuple(loaded.document.commands)
    if action == "scale":
        assert editor.canvas.apply_scale_factor(value)
    else:
        assert editor.canvas.apply_rotation_angle(value)
    after = session.snapshot
    assert after.groups[0] == renamed and len(after.groups) == 2
    assert after.groups[1].group_id != old_group.group_id
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation() and session.snapshot == before


@pytest.mark.parametrize("action", ["scale", "rotate"])
def test_group_affine_copy_candidate_failure_keeps_state_and_can_retry(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.exceptions import ValidationError
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.group_button.click()
    session = editor.canvas.collection_session
    assert session is not None
    before, checkpoint, history = (
        session.snapshot,
        session.checkpoint(),
        tuple(loaded.document.commands),
    )

    def reject(*_args: object, **_kwargs: object) -> None:
        raise ValidationError("模拟候选失败")

    def execute() -> None:
        editor.canvas.selected_entity_ids = {line.entity_id}
        editor.canvas.begin_transform(action)
        editor.canvas.add_coordinate_point((0, 0), exact_point=True)
        if action == "scale":
            assert editor.canvas.enable_scale_copy() and editor.canvas.apply_scale_factor(2)
        else:
            assert editor.canvas.enable_rotation_copy() and editor.canvas.apply_rotation_angle(90)

    with monkeypatch.context() as failed:
        failed.setattr(session, "stage", reject)
        execute()
    assert "模拟候选失败" in editor.status_label.text()
    assert session.snapshot == before and session.checkpoint() == checkpoint
    assert tuple(loaded.document.commands) == history
    execute()
    assert len(session.snapshot.groups) == 2
    assert editor.canvas.undo_last_operation() and session.snapshot == before


@pytest.mark.parametrize("seed_block", [False, True])
def test_geometry_seed_moves_group_with_block_instance_and_previews(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, seed_block: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.sketch import Sketch
    from mycad.ui.drawing_collection_session import DrawingCollectionTransformPreview
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (4, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(
        services, loaded, saved, session_identity=cast("int", getattr(window, _SESSION_FIELD))
    )
    inner = LineEntity(uuid4().hex, (0, 0), (4, 0))
    definition = BlockDefinition(uuid4().hex, "B", (inner,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    refs = (
        DrawingObjectRef("geometry", source.entity_id, saved.sketch_id),
        DrawingObjectRef("block_instance", instance.instance_id),
    )
    group = DrawingGroup(uuid4().hex, refs)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=editor.canvas.local_to_screen((12, 10) if seed_block else (2, 0)),
    )
    assert editor.canvas.selected_entity_ids == (set() if seed_block else {source.entity_id})
    assert editor.canvas.selected_block_instance_ids == (
        {instance.instance_id} if seed_block else set()
    )
    assert editor.canvas.effective_group_selection() == frozenset(refs)
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    cast("Callable[..., None]", getattr(editor.canvas, _TRANSFORM_METHOD))((0, 3), commit=False)
    preview = getattr(editor.canvas, _PREVIEW_FIELD)
    assert isinstance(preview, DrawingCollectionTransformPreview)
    assert len(preview.payload.sketches) == 2
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None and session.snapshot.block_instances == (
        replace(instance, insertion_mm=(10, 13)),
    )
    assert session.snapshot.sketches[0].entities == (
        replace(source, start_mm=(0, 3), end_mm=(4, 3)),
    )
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.block_instances == (instance,) and session.snapshot.groups == (group,)


def test_rotated_group_move_keeps_attached_datum_and_block_together(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_blocks import expand_block
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import Sketch
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.drawing_collection_session import DrawingCollectionTransformPreview
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (4, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=cast("int", getattr(window, _SESSION_FIELD))
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 2),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (4, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    refs = (
        DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
        DrawingObjectRef("datum", datum.datum_id),
        DrawingObjectRef("block_instance", instance.instance_id),
    )
    group = DrawingGroup(uuid4().hex, refs)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    editor.canvas.set_background_sketches(services.kernel.sketches, view)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, -12))
    )
    assert editor.canvas.effective_group_selection() == frozenset(refs)
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    cast("Callable[..., None]", getattr(editor.canvas, _TRANSFORM_METHOD))((5, 7), commit=False)
    preview = getattr(editor.canvas, _PREVIEW_FIELD)
    assert isinstance(preview, DrawingCollectionTransformPreview)
    editor.canvas.add_coordinate_point((5, 7), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None
    moved_line = session.snapshot.sketches[0].entities[0]
    moved_datum = session.snapshot.datums[0]
    moved_instance = session.snapshot.block_instances[0]
    assert isinstance(moved_line, LineEntity) and moved_line.start_mm == pytest.approx((-7, 5))
    assert moved_datum.position_mm == pytest.approx((-4, 7))
    assert moved_datum.target_mm == pytest.approx((-7, 5))
    assert moved_instance.insertion_mm == pytest.approx((3, 15))
    assert preview.payload.datums == (moved_datum,)
    preview_block = next(
        item for item in preview.payload.sketches if item.sketch_id == instance.instance_id
    )
    assert (
        preview_block.entities
        == expand_block(definition, moved_instance, session.snapshot.text_styles).entities
    )
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.datums == (datum,) and session.snapshot.block_instances == (instance,)


@pytest.mark.parametrize("change", [{"locked": True}, {"visible": False}, {"frozen": True}])
def test_group_move_from_geometry_rejects_unavailable_block_layer_on_canvas(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, change: dict[str, bool]
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.sketch import Sketch
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("BlockLayer"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    source = LineEntity(uuid4().hex, (0, 0), (4, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,), layers=layers)
    app.commit_new_sketch(
        services, loaded, saved, session_identity=cast("int", getattr(window, _SESSION_FIELD))
    )
    inner = LineEntity(uuid4().hex, (0, 0), (4, 0))
    definition = BlockDefinition(uuid4().hex, "B", (inner,), ())
    instance = BlockInstance(
        uuid4().hex, definition.definition_id, (10, 10), layer_name="BlockLayer"
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", source.entity_id, saved.sketch_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    restricted = layers.replace(replace(layers.get("BlockLayer"), **change))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": restricted.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    before, history = app.drawing_collection_snapshot(services), tuple(loaded.document.commands)
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((2, 0))
    )
    assert editor.canvas.selected_entity_ids == {source.entity_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert "图层" in editor.canvas.message or "图层" in editor.status_label.text()
    assert app.drawing_collection_snapshot(services) == before
    assert tuple(loaded.document.commands) == history
    if editor.canvas.collection_session is not None:
        assert editor.canvas.collection_session.snapshot.sketches[0].entities == (source,)
        assert editor.canvas.collection_session.snapshot.block_instances == (instance,)


@pytest.mark.parametrize("action", ["scale", "rotate"])
@pytest.mark.parametrize("change", [{"locked": True}, {"visible": False}, {"frozen": True}])
def test_group_affine_copy_rejects_unavailable_block_layer_atomically(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, action: str, change: dict[str, bool]
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.sketch import Sketch
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("BlockLayer"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (4, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), layers=layers)
    app.commit_new_sketch(
        services, loaded, saved, session_identity=cast("int", getattr(window, _SESSION_FIELD))
    )
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ())
    instance = BlockInstance(
        uuid4().hex, definition.definition_id, (10, 10), layer_name="BlockLayer"
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, saved.sketch_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    restricted = layers.replace(replace(layers.get("BlockLayer"), **change))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": restricted.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    before, history = app.drawing_collection_snapshot(services), tuple(loaded.document.commands)
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((2, 0))
    )
    assert editor.canvas.selected_entity_ids == {line.entity_id}
    editor.canvas.begin_transform(action)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    if action == "scale":
        assert editor.canvas.enable_scale_copy() and editor.canvas.apply_scale_factor(2)
    else:
        assert editor.canvas.enable_rotation_copy() and editor.canvas.apply_rotation_angle(90)
    assert "图层" in editor.canvas.message or "图层" in editor.status_label.text()
    assert app.drawing_collection_snapshot(services) == before
    assert tuple(loaded.document.commands) == history
    session = editor.canvas.collection_session
    if session is not None:
        assert session.snapshot.groups == (group,) and session.snapshot.block_instances == (
            instance,
        )


def test_click_text_only_block_selects_instance(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    text = DrawingText(uuid4().hex, "Block text", (0, 0))
    definition = BlockDefinition(uuid4().hex, "T", (), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    tools = editor.canvas.text_tools
    assert tools is not None
    item = editor.canvas.drawing_block_view().texts[0].text
    corners = tools.model_corners(item)
    center = (sum(p[0] for p in corners) / 4, sum(p[1] for p in corners) / 4)
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(center)
    )
    assert editor.canvas.selected_block_instance_ids == {instance.instance_id}
    assert tools.selected_ids == set()


@pytest.mark.parametrize("crossing", [False, True])
def test_window_selection_picks_whole_block_instances(qtbot: object, crossing: bool) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(700, 500)
    canvas.show()
    first = LineEntity(uuid4().hex, (-4, 0), (4, 0))
    second = LineEntity(uuid4().hex, (-30, 4), (30, 4))
    a = BlockDefinition(uuid4().hex, "A", (first,), ())
    b = BlockDefinition(uuid4().hex, "B", (second,), ())
    first_instance = BlockInstance(uuid4().hex, a.definition_id, (0, 0))
    second_instance = BlockInstance(uuid4().hex, b.definition_id, (0, 0))
    canvas.set_drawing_blocks((a, b), (first_instance, second_instance), TextStyleTable())
    assert canvas.set_tool("选择元素")
    first_point, second_point = ((10, 8), (-10, -8)) if crossing else ((-10, 8), (10, -8))
    start, end = canvas.local_to_screen(first_point), canvas.local_to_screen(second_point)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    expected = (
        {first_instance.instance_id, second_instance.instance_id}
        if crossing
        else {first_instance.instance_id}
    )
    assert canvas.selected_block_instance_ids == expected
    assert canvas.selected_entity_ids == set()


@pytest.mark.parametrize("crossing", [False, True])
def test_block_box_selection_with_far_text_respects_whole_instance(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, crossing: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (-4, 0), (4, 0))
    text = DrawingText(uuid4().hex, "Far", (1e20, 1e20))
    definition = BlockDefinition(uuid4().hex, "Mixed", (line,), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    editor.canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    assert editor.canvas.set_tool("选择元素")
    first, second = ((10, 8), (-10, -8)) if crossing else ((-10, 8), (10, -8))
    start, end = editor.canvas.local_to_screen(first), editor.canvas.local_to_screen(second)
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert editor.canvas.selected_block_instance_ids == (
        {instance.instance_id} if crossing else set()
    )


@pytest.mark.parametrize("box", [False, True])
def test_start_move_before_picking_block(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, box: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.begin_transform("move")
    assert editor.canvas.transform_selecting
    if box:
        start, end = editor.canvas.local_to_screen((8, 12)), editor.canvas.local_to_screen((17, 8))
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(editor.canvas, end)
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    else:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((12, 10))
        )
    assert editor.canvas.selected_block_instance_ids == {instance.instance_id}
    QTest.keyClick(editor.canvas, Qt.Key.Key_Return)
    assert not editor.canvas.transform_selecting
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 5), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None and session.snapshot.block_instances == (
        replace(instance, insertion_mm=(10, 15)),
    )


@pytest.mark.parametrize("preselect", [False, True])
def test_erase_command_removes_selected_block_and_undoes(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, preselect: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (5, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    assert editor.canvas.set_tool("选择元素")
    if preselect:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((12, 10))
        )
        assert editor.canvas.selected_block_instance_ids == {instance.instance_id}
    editor.drawing_command_bar.input.setText("ERASE")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    if not preselect:
        assert editor.canvas.transform_selecting
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((12, 10))
        )
        QTest.keyClick(editor.canvas, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and session.snapshot.block_instances == ()
    assert session.snapshot.block_definitions == (definition,)
    assert editor.canvas.undo_last_operation() and session.snapshot.block_instances == (instance,)


def test_group_command_accepts_block_instance_and_geometry(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingObjectRef
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (5, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    assert editor.canvas.replace_draft_entities((line,))
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((2, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.local_to_screen((12, 10)),
    )
    assert editor.canvas.selected_entity_ids == {line.entity_id}
    assert editor.canvas.selected_block_instance_ids == {instance.instance_id}
    editor.drawing_command_bar.input.setText("GROUP")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1
    assert set(session.snapshot.groups[0].members) == {
        DrawingObjectRef("geometry", line.entity_id, editor.draft_sketch_id),
        DrawingObjectRef("block_instance", instance.instance_id),
    }
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == ()


def test_unsupported_block_mirror_and_offset_are_rejected(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (5, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((12, 10))
    )
    editor.canvas.begin_transform("mirror")
    assert editor.canvas.active_transform is None and "块" in editor.canvas.message
    editor.canvas.begin_interactive_offset()
    assert editor.canvas.active_transform is None and "块" in editor.canvas.message
    assert services.kernel.drawing_block_instances == (instance,)


def test_rotated_rectangle_group_copy_with_block_reuses_preview_and_reopens(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingObjectRef
    from mycad.core.persistence import save_document
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.ui.drawing_collection_session import DrawingCollectionAffinePreview
    from mycad.ui.main_window import MainWindow

    bot = cast("QtBot", qtbot)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    bot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    member = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Block", (member,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (4, 2))
    assert editor.canvas.replace_draft_entities((rectangle,))
    editor.canvas.selected_entity_ids = {rectangle.entity_id}
    editor.group_button.click()
    session = editor.canvas.collection_session
    assert session is not None
    original = session.snapshot.groups[0]
    group = replace(
        original,
        members=(*original.members, DrawingObjectRef("block_instance", instance.instance_id)),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.update", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    editor.canvas.selected_entity_ids = {rectangle.entity_id}
    editor.canvas.begin_transform("rotate")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    assert editor.canvas.enable_rotation_copy()
    transform = cast("Callable[..., None]", getattr(type(editor.canvas), _TRANSFORM_METHOD))
    transform(editor.canvas, (1, 1), commit=False)
    preview = cast("DrawingCollectionAffinePreview | None", getattr(editor.canvas, _PREVIEW_FIELD))
    assert preview is not None and session.snapshot == before
    preview_ids = {
        item.entity_id for sketch in preview.payload.sketches for item in sketch.entities
    }
    assert preview_ids
    assert editor.canvas.apply_rotation_angle(45)
    after = session.snapshot
    assert len(after.groups) == len(after.block_instances) == 2
    assert after.groups[0] == group and instance in after.block_instances
    copied_ref = next(item for item in after.groups[1].members if item.kind == "geometry")
    assert copied_ref.object_id in preview_ids and copied_ref.object_id != rectangle.entity_id
    copied = next(
        item
        for sketch in after.sketches
        for item in sketch.entities
        if item.entity_id == copied_ref.object_id
    )
    assert isinstance(copied, PolylineEntity)
    assert next(item for item in after.block_instances if item != instance).definition_id == (
        instance.definition_id
    )
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    editor.finish_sketch()
    bot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
    )
    path = cast("Path", tmp_path) / "rectangle-block-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_far_offset_small_rectangle_block_fits_selects_and_snaps(qtbot: object) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    cast("QtBot", qtbot).addWidget(canvas)
    canvas.resize(600, 400)
    definition = BlockDefinition(
        uuid4().hex,
        "Far rectangle",
        (RectangleEntity(uuid4().hex, (1e9, 1e9), (1e9 + 1, 1e9 + 2)),),
        (),
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 7), 30)
    canvas.set_drawing_blocks((definition,), (instance,), TextStyleTable())
    canvas.fit_view()
    canvas.show()
    view = canvas.drawing_block_view()
    assert len(view.geometry) == 1
    entity = view.geometry[0].entity
    assert isinstance(entity, PolylineEntity)
    points = [canvas.local_to_screen(point) for point in entity.points_mm]
    assert all(canvas.rect().contains(point) for point in points)
    assert canvas.set_tool("选择元素")
    start, end = points[:2]
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        pos=QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2),
    )
    assert canvas.selected_block_instance_ids == {instance.instance_id}
    candidates = cast("Callable[[], list[tuple[Point2D, str]]]", getattr(canvas, _SNAP_METHOD))()
    assert any(kind == "端点" and point == entity.points_mm[0] for point, kind in candidates)


def test_rotated_group_clipboard_preserves_attached_datum_and_block(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import Sketch
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (4, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=cast("int", getattr(window, _SESSION_FIELD))
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 2),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (4, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    editor.canvas.set_background_sketches(services.kernel.sketches, view)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    try:
        assert editor.canvas.copy_to_clipboard()
        assert editor.canvas.begin_clipboard_paste()
        monkeypatch.setattr(editor.canvas, "_cursor", (5.0, 7.0))
        editor.canvas.grab()
        preview = editor.canvas.collection_paste_preview
        assert preview is not None and len(preview.payload.datums) == 1
        editor.canvas.add_coordinate_point((5, 7), exact_point=True)
        session = editor.canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 2
        copied_group = session.snapshot.groups[-1]
        copied_geometry = next(ref for ref in copied_group.members if ref.kind == "geometry")
        copied_datum_ref = next(ref for ref in copied_group.members if ref.kind == "datum")
        copied_datum = next(
            d for d in session.snapshot.datums if d.datum_id == copied_datum_ref.object_id
        )
        assert copied_datum.attachment is not None
        assert copied_datum.attachment.sketch_id == copied_geometry.sketch_id
        assert copied_datum.attachment.reference.entity_id == copied_geometry.object_id
        assert copied_datum == preview.payload.datums[0]
        assert editor.canvas.undo_last_operation() and session.snapshot.groups == (group,)
    finally:
        QApplication.clipboard().clear()


@pytest.mark.parametrize("select_dimension", [False, True])
@pytest.mark.parametrize("duplicate_identity", [False, True])
@pytest.mark.parametrize("mixed_kind", ["none", "text", "tolerance", "both"])
def test_rotated_partial_group_clipboard_preserves_dimensions(
    qtbot: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
    select_dimension: bool,
    duplicate_identity: bool,
    mixed_kind: str,
) -> None:
    from pathlib import Path

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.drawing_text import DrawingText
    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    other = LineEntity(uuid4().hex, (0, 20), (20, 20))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, -5),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, other), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    if duplicate_identity:
        duplicate = Sketch(
            uuid4().hex,
            WorkPlaneFrame.xy(),
            (LineEntity(line.entity_id, (0, 40), (20, 40)),),
            (replace(dimension, position_mm=(10, 35)),),
        )
        app.commit_new_sketch(services, loaded, duplicate, session_identity=0)
    text = DrawingText(uuid4().hex, "Label", (0, 10))
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (20, 10))
    if mixed_kind in {"text", "both"}:
        loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    if mixed_kind in {"tolerance", "both"}:
        loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
    original_sketches = services.kernel.sketches
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("geometry", other.entity_id, sketch.sketch_id),
        ),
        selectable=False,
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    if not select_dimension:
        dimension_group = DrawingGroup(
            uuid4().hex,
            (DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id),),
        )
        loaded.bus.execute("drawing.group.create", dimension_group.to_mapping(), "local")
    original_groups = services.kernel.drawing_groups
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    editor.canvas.set_background_sketches(services.kernel.sketches, view)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.selected_constraint_ids = {dimension.constraint_id} if select_dimension else set()
    try:
        if duplicate_identity:
            QApplication.clipboard().setText("unchanged")
            assert not editor.canvas.copy_to_clipboard()
            assert QApplication.clipboard().text() == "unchanged"
            editor.canvas.selected_entity_ids = set()
            editor.canvas.set_tool("选择元素")
            assert editor.canvas.rect().contains(editor.canvas.local_to_screen((0, -4)))
            QTest.mouseClick(
                editor.canvas,
                Qt.MouseButton.LeftButton,
                pos=editor.canvas.local_to_screen((0, -4)),
            )
            assert editor.canvas.selected_geometry_refs == {
                DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id)
            }
            if select_dimension:
                QTest.mouseClick(
                    editor.canvas,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.ControlModifier,
                    editor.canvas.local_to_screen((-5, -10)),
                )
                assert editor.canvas.selected_dimension_refs == {
                    DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id)
                }
        if mixed_kind in {"text", "both"}:
            assert editor.canvas.text_tools is not None
            editor.canvas.text_tools.selected_ids = {text.text_id}
        if mixed_kind in {"tolerance", "both"}:
            tools = editor.canvas.geometric_tolerance_tools
            assert tools is not None
            tools.selected_ids, tools.selected_id, tools.selected_kind = (
                {frame.frame_id},
                frame.frame_id,
                "frame",
            )
        if mixed_kind != "none":
            previous_capture = editor.canvas.capture_collection_clipboard
            assert previous_capture is not None

            def fail_capture(_include_dimensions: bool) -> tuple[bytes, bool]:
                raise ValueError("测试候选失败")

            QApplication.clipboard().setText("unchanged")
            editor.canvas.capture_collection_clipboard = fail_capture
            assert not editor.canvas.copy_to_clipboard()
            assert QApplication.clipboard().text() == "unchanged"
            assert services.kernel.sketches == original_sketches
            editor.canvas.capture_collection_clipboard = previous_capture
        assert editor.canvas.copy_to_clipboard(), editor.canvas.message
        assert editor.canvas.begin_clipboard_paste()
        monkeypatch.setattr(editor.canvas, "_cursor", (5.0, 7.0))
        editor.canvas.grab()
        preview = editor.canvas.collection_paste_preview
        assert preview is not None
        editor.canvas.add_coordinate_point((5, 7), exact_point=True)
        session = editor.canvas.collection_session
        assert session is not None
        assert session.snapshot.groups == original_groups
        copied = next(
            item
            for item in session.snapshot.sketches
            if item.sketch_id
            not in {*(s.sketch_id for s in original_sketches), editor.draft_sketch_id}
        )
        assert len(copied.constraints) == 1
        assert copied.constraints[0].references[0].entity_id == copied.entities[0].entity_id
        assert copied in preview.payload.sketches
        if mixed_kind in {"text", "both"}:
            assert len(session.snapshot.texts) == 2
            assert session.snapshot.texts[-1].text == text.text
            assert session.snapshot.texts[-1] in preview.payload.texts
        if mixed_kind in {"tolerance", "both"}:
            assert len(session.snapshot.frames) == 2
            assert session.snapshot.frames[-1].rows == frame.rows
            assert session.snapshot.frames[-1] in preview.payload.frames
        assert editor.canvas.undo_last_operation()
        assert editor.canvas.redo_last_operation()
        unit = window.execution_unit
        assert unit is not None
        editor.finish_sketch()
        cast("QtBot", qtbot).waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor,
            timeout=15000,
        )
        path = cast("Path", tmp_path) / "partial-group.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        reopened.bus.undo_operation()
        assert services.kernel.drawing_groups == original_groups
        assert services.kernel.sketches == original_sketches
        reopened.bus.redo_operation()
        assert copied in services.kernel.sketches
        assert services.kernel.drawing_groups == original_groups
    finally:
        QApplication.clipboard().clear()


def test_rotated_partial_group_mixed_clipboard_pastes_across_documents(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    from pathlib import Path

    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.geometric_tolerance import (
        DatumAttachment,
        DatumIdentifier,
        DatumReference,
        FeatureControlFrame,
        ToleranceRow,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    bot = cast("QtBot", qtbot)
    source_services = app.build_app(discoverers=[])
    source_window = MainWindow(services=source_services)
    monkeypatch.setattr(type(source_window.viewport), "paintGL", _skip_gl_paint)
    bot.addWidget(source_window)
    source_window.show()
    source_window.act_new_drawing.trigger()
    editor, source = source_window.active_sketch_dialog(), source_window.loaded_document()
    assert editor is not None and source is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    other = LineEntity(uuid4().hex, (0, 20), (20, 20))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, -5),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, other), (dimension,))
    app.commit_new_sketch(source_services, source, sketch, session_identity=0)
    text = DrawingText(uuid4().hex, "Label", (0, 10))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 2),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (20, 10),
    )
    source.bus.execute("drawing.text.add", text.to_mapping(), "local")
    source.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("geometry", other.entity_id, sketch.sketch_id),
        ),
        selectable=False,
    )
    source.bus.execute("drawing.group.create", group.to_mapping(), "local")
    cast("Callable[[], None]", getattr(source_window, _SYNC_METHOD))()
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: view)
    editor.canvas.set_background_sketches(source_services.kernel.sketches, view)
    editor.canvas.set_source_context_revision(source.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    text_tools, tolerance_tools = editor.canvas.text_tools, editor.canvas.geometric_tolerance_tools
    assert text_tools is not None and tolerance_tools is not None
    text_tools.selected_ids = {text.text_id}
    tolerance_tools.selected_ids, tolerance_tools.selected_id, tolerance_tools.selected_kind = (
        {frame.frame_id, datum.datum_id},
        frame.frame_id,
        "frame",
    )
    try:
        assert editor.canvas.copy_to_clipboard(), editor.canvas.message
        target_services = app.build_app(discoverers=[])
        target_window = MainWindow(services=target_services)
        monkeypatch.setattr(type(target_window.viewport), "paintGL", _skip_gl_paint)
        bot.addWidget(target_window)
        target_window.show()
        target_window.act_new_drawing.trigger()
        target_editor, target = (
            target_window.active_sketch_dialog(),
            target_window.loaded_document(),
        )
        unit = target_window.execution_unit
        assert target_editor is not None and target is not None and unit is not None
        monkeypatch.setattr(target_editor, "current_frame", lambda: view)
        target_editor.canvas.set_background_sketches(target_services.kernel.sketches, view)
        assert target_editor.canvas.begin_clipboard_paste()
        monkeypatch.setattr(target_editor.canvas, "_cursor", (50.0, 50.0))
        target_editor.canvas.grab()
        preview = target_editor.canvas.collection_paste_preview
        assert preview is not None
        target_editor.canvas.add_coordinate_point((50, 50), exact_point=True)
        session = target_editor.canvas.collection_session
        assert session is not None and session.snapshot.groups == ()
        copied_sketch = next(item for item in session.snapshot.sketches if item.entities)
        copied_line = copied_sketch.entities[0]
        assert isinstance(copied_line, LineEntity)
        assert copied_sketch.constraints[0].references[0].entity_id == copied_line.entity_id
        assert copied_sketch in preview.payload.sketches
        copied_text, copied_frame = session.snapshot.texts[0], session.snapshot.frames[0]
        copied_datum = session.snapshot.datums[0]
        assert copied_datum.attachment is not None
        assert copied_datum.attachment.sketch_id == copied_sketch.sketch_id
        assert copied_datum.attachment.reference.entity_id == copied_line.entity_id
        assert copied_frame.rows[0].datums[0].datum_id == copied_datum.datum_id
        assert copied_datum in preview.payload.datums
        assert copied_text in preview.payload.texts and copied_frame in preview.payload.frames
        start = copied_sketch.frame.local_to_world(copied_line.start_mm)
        assert (
            copied_text.position_mm[0] - start[0],
            copied_text.position_mm[1] - start[1],
        ) == pytest.approx((0, 10))
        assert (
            copied_frame.position_mm[0] - start[0],
            copied_frame.position_mm[1] - start[1],
        ) == pytest.approx((20, 10))
        assert target.document.commands == ()
        target_editor.finish_sketch()
        bot.waitUntil(
            lambda: not unit.is_busy and target_window.active_sketch_dialog() is not target_editor,
            timeout=15000,
        )
        path = cast("Path", tmp_path) / "mixed-partial-group-cross-document.my2d"
        save_document(target.document, path)
        reopened = app.open_app_document(target_services, path)
        reopened.bus.undo_operation()
        assert target_services.kernel.sketches == ()
        assert target_services.kernel.drawing_texts == ()
        assert target_services.kernel.drawing_tolerance_frames == ()
        assert target_services.kernel.drawing_datum_identifiers == ()
        reopened.bus.redo_operation()
        assert copied_sketch in target_services.kernel.sketches
        assert target_services.kernel.drawing_texts == (copied_text,)
        assert target_services.kernel.drawing_tolerance_frames == (copied_frame,)
        assert target_services.kernel.drawing_datum_identifiers == (copied_datum,)
    finally:
        QApplication.clipboard().clear()


def test_group_clipboard_external_datum_same_and_cross_document(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    from pathlib import Path

    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.geometric_tolerance import (
        DatumIdentifier,
        DatumReference,
        FeatureControlFrame,
        ToleranceRow,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch
    from mycad.ui.main_window import MainWindow

    bot = cast("QtBot", qtbot)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    bot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(uuid4().hex, "A", (0, 5), (0, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (10, 5),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {
            "add_datums": [datum.to_mapping()],
            "add_frames": [frame.to_mapping()],
        },
        "local",
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("tolerance", frame.frame_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    try:
        assert editor.canvas.copy_to_clipboard(), editor.canvas.message
        assert editor.canvas.begin_clipboard_paste()
        assert "解除" not in editor.canvas.message
        editor.canvas.add_coordinate_point((20, 0), exact_point=True)
        same = editor.canvas.collection_session
        assert same is not None and len(same.snapshot.groups) == 2
        assert same.snapshot.frames[-1].rows[0].datums[0].datum_id == datum.datum_id
        assert same.snapshot.datums == (datum,)
        assert editor.canvas.undo_last_operation()
        assert editor.canvas.redo_last_operation()
        copied_frame = same.snapshot.frames[-1]
        unit = window.execution_unit
        assert unit is not None
        editor.finish_sketch()
        bot.waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
        )
        next_editor = window.active_sketch_dialog()
        assert next_editor is not None and next_editor is not editor
        assert next_editor.canvas.begin_clipboard_paste()
        assert "解除" not in next_editor.canvas.message
        next_editor.canvas.add_coordinate_point((30, 0), exact_point=True)
        next_session = next_editor.canvas.collection_session
        assert next_session is not None
        assert next_session.snapshot.frames[-1].rows[0].datums[0].datum_id == datum.datum_id
        assert next_editor.canvas.undo_last_operation()
        source_path = cast("Path", tmp_path) / "external-source.my2d"
        save_document(loaded.document, source_path)
        reopened = app.open_app_document(services, source_path)
        reopened.bus.undo_operation()
        assert services.kernel.drawing_tolerance_frames == (frame,)
        assert services.kernel.drawing_datum_identifiers == (datum,)
        reopened.bus.redo_operation()
        assert services.kernel.drawing_tolerance_frames[-1] == copied_frame
        assert copied_frame.rows[0].datums[0].datum_id == datum.datum_id
        target_services = app.build_app(discoverers=[])
        target_window = MainWindow(services=target_services)
        monkeypatch.setattr(type(target_window.viewport), "paintGL", _skip_gl_paint)
        bot.addWidget(target_window)
        target_window.show()
        target_window.act_new_drawing.trigger()
        target_editor, target_loaded = (
            target_window.active_sketch_dialog(),
            target_window.loaded_document(),
        )
        target_unit = target_window.execution_unit
        assert target_editor is not None and target_loaded is not None and target_unit is not None
        assert target_editor.canvas.begin_clipboard_paste()
        assert "外部标注关联" in target_editor.canvas.message
        target_editor.canvas.add_coordinate_point((20, 0), exact_point=True)
        target = target_editor.canvas.collection_session
        assert target is not None and len(target.snapshot.groups) == 1
        assert target.snapshot.frames[0].rows[0].datums[0].datum_id is None
        assert target.snapshot.frames[0].rows[0].datums[0].label == "A"
        assert target.snapshot.datums == ()
        assert "解除" in target_editor.canvas.message
        cross_frame = target.snapshot.frames[0]
        target_editor.finish_sketch()
        bot.waitUntil(
            lambda: (
                not target_unit.is_busy
                and target_window.active_sketch_dialog() is not target_editor
            ),
            timeout=15000,
        )
        target_path = cast("Path", tmp_path) / "external-target.my2d"
        save_document(target_loaded.document, target_path)
        target_reopened = app.open_app_document(target_services, target_path)
        target_reopened.bus.undo_operation()
        assert target_services.kernel.drawing_tolerance_frames == ()
        target_reopened.bus.redo_operation()
        assert target_services.kernel.drawing_tolerance_frames == (cross_frame,)
    finally:
        QApplication.clipboard().clear()


def test_external_clipboard_tracks_live_document_across_workspace_switches(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.geometric_tolerance import (
        DatumIdentifier,
        DatumReference,
        FeatureControlFrame,
        ToleranceRow,
    )
    from mycad.core.sketch import Sketch
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    source = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(source.services, source.loaded, sketch, session_identity=0)
    datum = DatumIdentifier(uuid4().hex, "A", (0, 5), (0, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (10, 5),
    )
    source.loaded.bus.execute(
        "drawing.tolerance.batch",
        {
            "add_datums": [datum.to_mapping()],
            "add_frames": [frame.to_mapping()],
        },
        "local",
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("tolerance", frame.frame_id),
        ),
    )
    source.loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(source.loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    try:
        assert editor.canvas.copy_to_clipboard(), editor.canvas.message
        target = window.new_session_document("sketch")
        target_editor = window.active_sketch_dialog()
        assert target_editor is not None
        assert target_editor.canvas.begin_clipboard_paste()
        assert "外部标注关联" in target_editor.canvas.message
        target_editor.canvas.add_coordinate_point((20, 0), exact_point=True)
        target_session = target_editor.canvas.collection_session
        assert target_session is not None
        assert target_session.snapshot.frames[-1].rows[0].datums[0].datum_id is None
        window.activate_session_document(source.loaded.document.document_id)
        source_editor = window.active_sketch_dialog()
        assert source_editor is not None
        assert source_editor.canvas.begin_clipboard_paste()
        assert "解除" not in source_editor.canvas.message
        source_editor.canvas.add_coordinate_point((20, 0), exact_point=True)
        source_session = source_editor.canvas.collection_session
        assert source_session is not None
        assert source_session.snapshot.frames[-1].rows[0].datums[0].datum_id == datum.datum_id
        assert target.loaded.document.commands == ()
    finally:
        QApplication.clipboard().clear()


def test_group_clipboard_changed_external_target_fails_and_can_retry(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from pytestqt.qtbot import QtBot

    from mycad import app
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.geometric_tolerance import (
        DatumIdentifier,
        DatumReference,
        FeatureControlFrame,
        ToleranceRow,
    )
    from mycad.core.sketch import Sketch
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    cast("QtBot", qtbot).addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(uuid4().hex, "A", (0, 5), (0, 0))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (10, 5),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch",
        {
            "add_datums": [datum.to_mapping()],
            "add_frames": [frame.to_mapping()],
        },
        "local",
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("tolerance", frame.frame_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    try:
        assert editor.canvas.copy_to_clipboard(), editor.canvas.message
        changed = replace(datum, position_mm=(0, 8))
        loaded.bus.execute(
            "drawing.tolerance.batch", {"update_datums": [changed.to_mapping()]}, "local"
        )
        cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
        editor.canvas.set_source_context_revision(loaded.document.revision)
        before = app.drawing_collection_snapshot(services)
        history = loaded.document.commands
        assert editor.canvas.begin_clipboard_paste()
        editor.canvas.add_coordinate_point((20, 0), exact_point=True)
        assert editor.canvas.clipboard_paste_active
        assert "变化" in editor.canvas.message
        assert app.drawing_collection_snapshot(services) == before
        assert loaded.document.commands == history
        session = editor.canvas.collection_session
        assert session is not None
        assert session.snapshot.groups == (group,)
        QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
        assert not editor.canvas.clipboard_paste_active
        editor.canvas.selected_entity_ids = {line.entity_id}
        assert editor.canvas.copy_to_clipboard(), editor.canvas.message
        assert editor.canvas.begin_clipboard_paste()
        editor.canvas.add_coordinate_point((20, 0), exact_point=True)
        session = editor.canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 2
        assert session.snapshot.frames[-1].rows[0].datums[0].datum_id == changed.datum_id
        assert session.snapshot.datums == (changed,)
    finally:
        QApplication.clipboard().clear()
