# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimension lines and extension lines retain their drawing roles."""

from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.drawing_dimension_styles import DrawingDimensionStylesDialog
from mycad.ui.sketch_editor import SketchCanvas


def test_linear_dimension_identifies_extension_lines(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.entities = [line]
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(5, 5),
    )
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None and len(layout.lines) == 3
    assert layout.extension_indices == (0, 1)


@pytest.mark.parametrize(
    ("first", "second", "roles"), ((True, False, (1,)), (False, True, (0,)), (True, True, ()))
)
@pytest.mark.parametrize("legacy", (False, True))
def test_hidden_extension_lines_leave_correct_visible_roles(
    qtbot: QtBot, first: bool, second: bool, roles: tuple[int, ...], legacy: bool
) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    style = DimensionStyle("A", suppress_extension_first=first, suppress_extension_second=second)
    canvas.entities = [line]
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=None if legacy else (5, 5),
        style_name=style.name,
    )
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None and len(layout.lines) == 1 + len(roles)
    assert layout.extension_roles == roles
    assert len(layout.arrows) == 2


@pytest.mark.parametrize(
    ("first", "second", "arrow_roles"), ((True, False, (1,)), (False, True, (0,)), (True, True, ()))
)
@pytest.mark.parametrize("legacy", (False, True))
def test_hidden_dimension_half_keeps_opposite_arrow_role(
    qtbot: QtBot, first: bool, second: bool, arrow_roles: tuple[int, ...], legacy: bool
) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    style = DimensionStyle(
        "A",
        arrow_first="closed",
        arrow_second="tick",
        suppress_dimension_first=first,
        suppress_dimension_second=second,
    )
    canvas.entities = [line]
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=None if legacy else (10, 5),
        style_name=style.name,
    )
    layout = canvas.dimension_layout(dim, canvas.dimension_entities())
    assert layout is not None and layout.arrow_roles == arrow_roles
    assert len(layout.arrows) == len(arrow_roles)
    assert len(layout.lines) == 2 + (0 if first and second else 1)
    if arrow_roles == (1,):
        assert len(canvas.dimension_arrow_segments(layout, 1, dim)) == 1


@pytest.mark.parametrize("position", ((8, 8), (-8, 8), (-8, -8), (8, -8)))
def test_angular_suppression_follows_first_reference(
    qtbot: QtBot, position: tuple[int, int]
) -> None:
    from dataclasses import replace

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    first = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, -10), (0, 10))
    canvas.entities = [first, second]
    style = DimensionStyle("A")
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    dim = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        90,
        "deg",
        driving=False,
        position_mm=position,
        style_name=style.name,
    )
    before = canvas.dimension_layout(dim, canvas.dimension_entities())
    assert before is not None
    roles = before.arrow_roles or (0, 1)
    second_arrow = before.arrows[roles.index(1)]
    hidden = replace(style, suppress_dimension_first=True)
    canvas.drawing_dimension_styles = DimensionStyleTable((hidden,), hidden.name)
    after = canvas.dimension_layout(dim, canvas.dimension_entities())
    assert after is not None and after.arrow_roles == (1,) and after.arrows == (second_arrow,)
    assert len(after.extension_indices) == 2 and len(after.lines) < len(before.lines)


def test_radius_suppression_keeps_center_mark(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    canvas.entities = [circle]
    style = DimensionStyle("A", center_mark="mark", suppress_dimension_first=True)
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    dim = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    layout = canvas.dimension_layout(dim, canvas.dimension_entities())
    assert layout is not None and len(layout.lines) == 2 and len(layout.extension_indices) == 2
    assert not layout.arrows


def test_arc_length_suppression_retains_second_arrow(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 90)
    canvas.entities = [arc]
    style = DimensionStyle("A", suppress_dimension_first=True, arrow_second="tick")
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    dim = SketchConstraint(
        uuid4().hex,
        "arc_length",
        (SketchGeometryReference(arc.entity_id, "geometry"),),
        15.7079632679,
        "mm",
        driving=False,
        position_mm=(12, 12),
        style_name=style.name,
    )
    layout = canvas.dimension_layout(dim, canvas.dimension_entities())
    assert layout is not None and layout.arrow_roles == (1,) and len(layout.extension_indices) == 2
    assert len(canvas.dimension_arrow_segments(layout, 1, dim)) == 1


def test_diameter_suppression_uses_arrow_ends_not_line_order(qtbot: QtBot) -> None:
    from dataclasses import replace

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    canvas.entities = [circle]
    style = DimensionStyle("A")
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    dim = SketchConstraint(
        uuid4().hex,
        "diameter",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    before = canvas.dimension_layout(dim, canvas.dimension_entities())
    assert before is not None
    style = replace(style, suppress_dimension_first=True)
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    after = canvas.dimension_layout(dim, canvas.dimension_entities())
    assert after is not None and after.arrow_roles == (1,) and after.arrows == (before.arrows[1],)
    assert after.lines[0][0] == before.lines[0][0]


def test_dimension_suppression_splits_at_moved_text(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    canvas.entities = [line]
    style = DimensionStyle("A", suppress_dimension_first=True)
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, 5),
        text_position_mm=(15, 5),
        style_name=style.name,
    )
    layout = canvas.dimension_layout(dim, canvas.dimension_entities())
    assert layout is not None
    main = [
        line
        for i, line in enumerate(layout.lines)
        if i not in layout.extension_indices and i not in layout.leader_indices
    ]
    assert len(main) == 1
    assert main[0][0] == canvas.local_to_screen((15, 5))
    assert main[0][1] == canvas.local_to_screen((20, 5))


def test_dimension_and_extension_suppression_compose(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    style = DimensionStyle(
        "A",
        suppress_dimension_first=True,
        suppress_extension_first=True,
        extension_linetype_second="DOTTED",
        arrow_second="tick",
    )
    canvas.entities = [line]
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(10, 5),
        style_name=style.name,
    )
    layout = canvas.dimension_layout(dim, canvas.dimension_entities())
    assert layout is not None and layout.extension_roles == (1,) and layout.arrow_roles == (1,)
    assert len(layout.lines) == 2 and len(canvas.dimension_arrow_segments(layout, 1, dim)) == 1


def test_radius_center_mark_uses_extension_line_role(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    canvas.entities = [circle]
    style = DimensionStyle("A", center_mark="line")
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None and len(layout.lines) == 7
    assert layout.extension_indices == (1, 2, 3, 4, 5, 6)


def test_dimension_style_dialog_stages_component_colors(qtbot: QtBot) -> None:
    style = DimensionStyle("A")
    dialog = DrawingDimensionStylesDialog(DimensionStyleTable((style,), style.name), frozenset())
    qtbot.addWidget(dialog)
    dialog.dimension_color.setCurrentIndex(dialog.dimension_color.findData(1))
    dialog.extension_color.setCurrentIndex(dialog.extension_color.findData(3))
    dialog.text_color.setCurrentIndex(dialog.text_color.findData(5))
    dialog.save_button.click()
    staged = dialog.table.current
    assert (staged.dimension_color, staged.extension_color, staged.text_color) == (1, 3, 5)


def test_dimension_style_dialog_stages_lineweights(qtbot: QtBot) -> None:
    style = DimensionStyle("A")
    dialog = DrawingDimensionStylesDialog(DimensionStyleTable((style,), style.name), frozenset())
    qtbot.addWidget(dialog)
    dialog.dimension_lineweight.setCurrentIndex(dialog.dimension_lineweight.findData(35))
    dialog.extension_lineweight.setCurrentIndex(dialog.extension_lineweight.findData(70))
    dialog.save_button.click()
    staged = dialog.table.current
    assert (staged.dimension_lineweight, staged.extension_lineweight) == (35, 70)


def test_dimension_style_dialog_stages_linetypes(qtbot: QtBot) -> None:
    style = DimensionStyle("A")
    dialog = DrawingDimensionStylesDialog(DimensionStyleTable((style,), style.name), frozenset())
    qtbot.addWidget(dialog)
    dialog.dimension_linetype.setCurrentIndex(dialog.dimension_linetype.findData("DASHED"))
    dialog.extension_linetype_first.setCurrentIndex(
        dialog.extension_linetype_first.findData("DOTTED")
    )
    dialog.extension_linetype_second.setCurrentIndex(
        dialog.extension_linetype_second.findData("DASHDOT")
    )
    dialog.save_button.click()
    staged = dialog.table.current
    assert (
        staged.dimension_linetype,
        staged.extension_linetype_first,
        staged.extension_linetype_second,
    ) == ("DASHED", "DOTTED", "DASHDOT")


def test_dimension_style_dialog_stages_hidden_extensions(qtbot: QtBot) -> None:
    style = DimensionStyle("A")
    dialog = DrawingDimensionStylesDialog(DimensionStyleTable((style,), style.name), frozenset())
    qtbot.addWidget(dialog)
    dialog.suppress_extension_first.setChecked(True)
    dialog.suppress_dimension_second.setChecked(True)
    dialog.save_button.click()
    assert dialog.table.current.suppress_extension_first
    assert not dialog.table.current.suppress_extension_second
    assert dialog.table.current.suppress_dimension_second


def test_dimension_lines_paint_with_separate_component_colors(qtbot: QtBot) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    from mycad.ui.sketch_editor import DimensionLayout

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    image = QImage(40, 40, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QPen(QColor("red"), 1))
    layout = DimensionLayout(
        ((QPointF(5, 5), QPointF(30, 5)), (QPointF(5, 15), QPointF(30, 15))), (), QPointF(), (1,)
    )
    try:
        canvas._draw_dimension_lines(painter, layout, 1, extension_pen=QPen(QColor("green"), 1))
    finally:
        painter.end()
    assert image.pixelColor(15, 5) == QColor("red")
    assert image.pixelColor(15, 15) == QColor("green")


def test_canvas_overlay_applies_all_three_style_colors(qtbot: QtBot) -> None:
    from PySide6.QtGui import QColor, QImage, QPainter

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(300, 200)
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    style = DimensionStyle("A", dimension_color=1, extension_color=3, text_color=5)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(0, 5),
        style_name=style.name,
    )
    canvas.entities = [line]
    canvas.constraints = [dimension]
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    image = QImage(300, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    try:
        canvas._draw_constraint_overlays(painter)
    finally:
        painter.end()
    colors = {image.pixelColor(x, y).name() for x in range(300) for y in range(200)}
    assert {"#ff0000", "#00ff00", "#0000ff"}.issubset(colors)
    canvas.selected_constraint_ids = {dimension.constraint_id}
    image.fill(QColor("white"))
    painter = QPainter(image)
    try:
        canvas._draw_constraint_overlays(painter)
    finally:
        painter.end()
    selected_colors = {image.pixelColor(x, y).name() for x in range(300) for y in range(200)}
    assert "#0091b4" in selected_colors
    assert {"#ff0000", "#00ff00", "#0000ff"}.isdisjoint(selected_colors)


def test_canvas_overlay_applies_component_lineweights(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    from mycad.ui.sketch_editor import DimensionLayout

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(300, 200)
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    style = DimensionStyle("A", dimension_lineweight=35, extension_lineweight=70)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(0, 5),
        style_name=style.name,
    )
    canvas.entities = [line]
    canvas.constraints = [dimension]
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    widths: list[tuple[float, float]] = []

    def capture(
        painter: QPainter,
        _layout: DimensionLayout,
        _scale: float,
        _constraint: SketchConstraint | None = None,
        *,
        extension_pen: QPen | None = None,
        second_extension_pen: QPen | None = None,
    ) -> None:
        assert extension_pen is not None
        assert second_extension_pen is not None
        widths.append((painter.pen().widthF(), extension_pen.widthF()))

    monkeypatch.setattr(canvas, "_draw_dimension_lines", capture)
    image = QImage(300, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    try:
        canvas._draw_constraint_overlays(painter)
    finally:
        painter.end()
    assert widths == [(pytest.approx(1.4), pytest.approx(2.8))]


def test_canvas_overlay_applies_three_linetypes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    from mycad.ui.sketch_editor import DimensionLayout

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(300, 200)
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    style = DimensionStyle(
        "A",
        dimension_linetype="DASHED",
        extension_linetype_first="DOTTED",
        extension_linetype_second="DASHDOT",
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(0, 5),
        style_name=style.name,
    )
    canvas.entities, canvas.constraints = [line], [dimension]
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    styles: list[tuple[Qt.PenStyle, Qt.PenStyle, Qt.PenStyle]] = []

    def capture(
        painter: QPainter,
        _layout: DimensionLayout,
        _scale: float,
        _constraint: SketchConstraint | None = None,
        *,
        extension_pen: QPen | None = None,
        second_extension_pen: QPen | None = None,
    ) -> None:
        assert extension_pen is not None and second_extension_pen is not None
        styles.append((painter.pen().style(), extension_pen.style(), second_extension_pen.style()))

    monkeypatch.setattr(canvas, "_draw_dimension_lines", capture)
    image = QImage(300, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    try:
        canvas._draw_constraint_overlays(painter)
    finally:
        painter.end()
    assert styles == [(Qt.PenStyle.DashLine, Qt.PenStyle.DotLine, Qt.PenStyle.DashDotLine)]


def test_first_and_second_extension_use_their_own_pen(qtbot: QtBot) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    from mycad.ui.sketch_editor import DimensionLayout

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    layout = DimensionLayout(
        ((QPointF(5, 5), QPointF(30, 5)), (QPointF(5, 15), QPointF(30, 15))), (), QPointF(), (0, 1)
    )
    try:
        canvas._draw_dimension_lines(
            painter,
            layout,
            1,
            extension_pen=QPen(QColor("red")),
            second_extension_pen=QPen(QColor("blue")),
        )
    finally:
        painter.end()
    assert image.pixelColor(15, 5) == QColor("red")
    assert image.pixelColor(15, 15) == QColor("blue")


def test_remaining_second_extension_uses_second_pen(qtbot: QtBot) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    from mycad.ui.sketch_editor import DimensionLayout

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    layout = DimensionLayout(((QPointF(5, 15), QPointF(30, 15)),), (), QPointF(), (0,), (1,))
    try:
        canvas._draw_dimension_lines(
            painter,
            layout,
            1,
            extension_pen=QPen(QColor("red")),
            second_extension_pen=QPen(QColor("blue")),
        )
    finally:
        painter.end()
    assert image.pixelColor(15, 15) == QColor("blue")


@pytest.mark.parametrize("kind", ("angle", "arc_length"))
@pytest.mark.parametrize("legacy", (False, True))
def test_curved_dimension_keeps_extension_roles(qtbot: QtBot, kind: str, legacy: bool) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    if kind == "angle":
        first = LineEntity(uuid4().hex, (0, 0), (10, 0))
        second = LineEntity(uuid4().hex, (0, 0), (0, 10))
        canvas.entities = [first, second]
        refs = (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        )
        unit, value = "deg", 90
    else:
        arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 90)
        canvas.entities = [arc]
        refs = (SketchGeometryReference(arc.entity_id, "geometry"),)
        unit, value = "mm", 15.7079632679
    dimension = SketchConstraint(
        uuid4().hex,
        kind,
        refs,
        value,
        unit,
        driving=False,
        position_mm=None if legacy else (12, 12),
    )
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    assert len(layout.extension_indices) == 2
    assert all(index >= len(layout.lines) - 2 for index in layout.extension_indices)


@pytest.mark.parametrize("kind", ("angle", "arc_length"))
def test_curved_dimension_hides_only_requested_extension(qtbot: QtBot, kind: str) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    if kind == "angle":
        first = LineEntity(uuid4().hex, (0, 0), (10, 0))
        second = LineEntity(uuid4().hex, (0, 0), (0, 10))
        canvas.entities = [first, second]
        refs = (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        )
        value, unit = 90, "deg"
    else:
        arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 90)
        canvas.entities = [arc]
        refs = (SketchGeometryReference(arc.entity_id, "geometry"),)
        value, unit = 15.7079632679, "mm"
    style = DimensionStyle("A", suppress_extension_first=True)
    canvas.drawing_dimension_styles = DimensionStyleTable((style,), style.name)
    dim = SketchConstraint(
        uuid4().hex,
        kind,
        refs,
        value,
        unit,
        driving=False,
        position_mm=(12, 12),
        style_name=style.name,
    )
    layout = canvas.dimension_layout(dim, canvas.dimension_entities())
    assert layout is not None and len(layout.extension_indices) == 1
    assert layout.extension_roles == (1,) and len(layout.arrows) == 2


def test_color_seven_adapts_to_canvas_theme() -> None:
    from mycad.ui.dimension_colors import indexed_color

    assert indexed_color(7, dark=False).name() == "#000000"
    assert indexed_color(7, dark=True).name() == "#ffffff"


def test_style_manager_applies_colors_and_undoes(qtbot: QtBot) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    original = services.kernel.drawing_dimension_styles

    def configure() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        dialog.dimension_color.setCurrentIndex(dialog.dimension_color.findData(1))
        dialog.extension_color.setCurrentIndex(dialog.extension_color.findData(3))
        dialog.text_color.setCurrentIndex(dialog.text_color.findData(5))
        dialog.save_button.click()
        dialog.accept()

    QTimer.singleShot(50, configure)
    window._open_drawing_dimension_styles(editor)
    style = services.kernel.drawing_dimension_styles.current
    assert (style.dimension_color, style.extension_color, style.text_color) == (1, 3, 5)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_dimension_styles == original
