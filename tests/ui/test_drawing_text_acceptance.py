# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Focused acceptance of layout anchors and editing/selection gaps."""

from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
from mycad.core.sketch_layers import SketchLayer
from mycad.ui.drawing_text_tools import DrawingTextTools
from mycad.ui.font_manager import FontManager
from mycad.ui.sketch_editor import SketchCanvas
from mycad.ui.text_layout import layout_text
from mycad.ui.text_style_dialog import TextStyleDialog


@pytest.mark.parametrize("vertical", ["top", "middle", "bottom"])
@pytest.mark.parametrize("horizontal", ["left", "center", "right"])
def test_layout_nine_anchors_and_scaled_height(
    qapp: QApplication, tmp_path: Path, vertical: str, horizontal: str
) -> None:
    manager = FontManager(tmp_path)
    style = TextStyle(font_family="DejaVu Sans", height_mm=4)
    if style.font_family not in manager.families():
        pytest.skip("Fixed font DejaVu Sans unavailable")
    item = DrawingText(uuid4().hex, "HHHH", (0, 0), align=f"{vertical}_{horizontal}")
    bounds = layout_text(item, style, manager).bounds
    assert {"top": bounds.top(), "middle": bounds.center().y(), "bottom": bounds.bottom()}[
        vertical
    ] == pytest.approx(0, abs=1e-8)
    assert {"left": bounds.left(), "center": bounds.center().x(), "right": bounds.right()}[
        horizontal
    ] == pytest.approx(0, abs=1e-8)
    scaled = layout_text(replace(item, height_mm=8), style, manager).bounds
    assert scaled.width() == pytest.approx(bounds.width() * 2, rel=1e-9)
    assert scaled.height() == pytest.approx(bounds.height() * 2, rel=1e-9)


@pytest.mark.parametrize("alignment", ["left", "center", "right"])
def test_baseline_horizontal_anchors(qapp: QApplication, tmp_path: Path, alignment: str) -> None:
    manager = FontManager(tmp_path)
    item = DrawingText(uuid4().hex, "HHHH", (0, 0), align=alignment)
    bounds = layout_text(item, TextStyle(font_family="DejaVu Sans", height_mm=4), manager).bounds
    assert {"left": bounds.left(), "center": bounds.center().x(), "right": bounds.right()}[
        alignment
    ] == pytest.approx(0, abs=1e-8)
    assert bounds.top() < -3.9 and bounds.bottom() > 0


def test_edit_cancel_and_invalid_empty_commit_preserve_object(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    tools = DrawingTextTools(canvas)
    item = DrawingText(uuid4().hex, "Original", (1, 2))
    tools.sync((item,), TextStyleTable())
    calls: list[dict[str, object]] = []
    tools.execute = lambda command, params: calls.append(params) is None
    tools.selected_ids = {item.text_id}
    tools.edit_selected()
    tools.editor.setPlainText("Changed")
    assert tools.cancel()
    assert tools.texts == (item,) and not calls
    tools.edit_selected()
    tools.editor.clear()
    tools.commit()
    assert tools.pending and tools.overlay.isVisible()
    assert tools.warning.text() and not calls
    assert tools.texts == (item,)


def test_visible_rotated_text_box_and_crossing_selection(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    canvas.layer_table = canvas.layer_table.add(SketchLayer("hidden", visible=False))
    tools = DrawingTextTools(canvas)
    visible = DrawingText(uuid4().hex, "ABC", (0, 0), rotation_deg=30)
    hidden = DrawingText(uuid4().hex, "ABC", (0, 0), layer_name="hidden")
    tools.sync((visible, hidden), TextStyleTable())
    bounds = tools.screen_bounds(visible)
    center_model = canvas.screen_to_local(bounds.center())
    assert tools.hit(center_model) == visible
    tools.select_box(
        bounds.topLeft() - QPointF(2, 2),
        bounds.bottomRight() + QPointF(2, 2),
        Qt.KeyboardModifier.NoModifier,
    )
    assert tools.selected_ids == {visible.text_id}
    tools.select_box(
        bounds.center() + QPointF(1, 1),
        bounds.topLeft() - QPointF(1, 1),
        Qt.KeyboardModifier.NoModifier,
    )
    assert tools.selected_ids == {visible.text_id}


def test_rotated_text_remains_pickable_after_canvas_zoom(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    tools = DrawingTextTools(canvas)
    item = DrawingText(uuid4().hex, "ABC", (2, 3), rotation_deg=37)
    tools.sync((item,), TextStyleTable())
    for factor in (0.5, 4.0, 0.5):
        canvas.zoom_view_factor(factor)
        point = canvas.screen_to_local(tools.screen_bounds(item).center())
        assert tools.hit(point) == item


def test_style_dialog_rejects_casefold_duplicate_and_empty_name(
    qapp: QApplication, tmp_path: Path
) -> None:
    styles = TextStyleTable((TextStyle("a", "Technical"), TextStyle("b", "Other")), "a")
    dialog = TextStyleDialog(styles, frozenset(), FontManager(tmp_path))
    dialog.styles.setCurrentIndex(dialog.styles.findData("b"))
    for invalid in ("technical", ""):
        dialog.name.setText(invalid)
        assert not dialog.save_style()
        assert dialog.message.text()
        assert dialog.table == styles
    dialog.name.setText("Renamed")
    assert dialog.save_style()
    assert dialog.table.get("b").name == "Renamed"


def test_double_click_existing_text_then_escape_is_nonmutating(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    tools = DrawingTextTools(canvas)
    item = DrawingText(uuid4().hex, "Original", (0, 0))
    tools.sync((item,), TextStyleTable())
    calls: list[dict[str, object]] = []
    tools.execute = lambda command, params: calls.append(params) is None
    QTest.mouseDClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.screen_bounds(item).center().toPoint()
    )
    assert tools.pending and tools.editor.toPlainText() == "Original"
    tools.editor.setPlainText("Changed")
    QTest.keyClick(tools.editor, Qt.Key.Key_Escape)
    assert not tools.pending and tools.texts == (item,) and not calls


def test_multiselection_layer_change_preserves_other_fields(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.layer_table = canvas.layer_table.add(SketchLayer("Notes"))
    tools = DrawingTextTools(canvas)
    items = (
        DrawingText(uuid4().hex, "A", (1, 2)),
        DrawingText(uuid4().hex, "B", (8, 9), rotation_deg=20),
    )
    tools.sync(items, TextStyleTable())
    tools.selected_ids = {item.text_id for item in items}
    tools.refresh_selection()
    calls: list[dict[str, object]] = []
    tools.execute = lambda command, params: calls.append(params) is None
    tools.layer_combo.setCurrentText("Notes")
    tools.apply_properties()
    raw = calls[0]["update"]
    assert isinstance(raw, list)
    assert tuple(DrawingText.from_mapping(value) for value in cast("list[object]", raw)) == tuple(
        replace(item, layer_name="Notes") for item in items
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("x", 55.0),
        ("y", 60.0),
        ("height_mm", 6.0),
        ("width_factor", 1.3),
        ("rotation_deg", 75.0),
        ("box_width_mm", 35.0),
        ("line_spacing", 1.5),
        ("align", "bottom_right"),
        ("style_id", "other"),
    ],
)
def test_multiselection_only_changes_the_chosen_property(
    qtbot: QtBot, field: str, value: float | str
) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tools = DrawingTextTools(canvas)
    styles = TextStyleTable((TextStyle(), TextStyle("other", "其他")))
    items = (
        DrawingText(uuid4().hex, "A", (1, 2), kind="mtext", height_mm=3, rotation_deg=20),
        DrawingText(
            uuid4().hex, "B", (8, 9), kind="mtext", style_id="other", height_mm=4, rotation_deg=40
        ),
    )
    tools.sync(items, styles)
    tools.selected_ids = {item.text_id for item in items}
    tools.refresh_selection()
    calls: list[dict[str, object]] = []
    tools.execute = lambda command, params: calls.append(params) is None
    controls = {
        "x": tools.x,
        "y": tools.y,
        "height_mm": tools.height,
        "width_factor": tools.width_factor,
        "rotation_deg": tools.rotation,
        "box_width_mm": tools.box_width,
        "line_spacing": tools.line_spacing,
    }
    if field == "align":
        tools.align.setCurrentIndex(tools.align.findData(value))
    elif field == "style_id":
        tools.style_combo.setCurrentIndex(tools.style_combo.findData(value))
    else:
        controls[field].setValue(cast("float", value))
    tools.apply_properties()
    assert len(calls) == 1
    raw = calls[0]["update"]
    assert isinstance(raw, list)
    for original, changed_raw in zip(items, cast("list[object]", raw), strict=True):
        changed = DrawingText.from_mapping(changed_raw)
        if field in {"x", "y"}:
            expected_position = (
                (value, original.position_mm[1])
                if field == "x"
                else (original.position_mm[0], value)
            )
            assert changed.position_mm == expected_position
            assert replace(changed, position_mm=original.position_mm) == original
        else:
            assert getattr(changed, field) == value
            assert replace(changed, **{field: getattr(original, field)}) == original
