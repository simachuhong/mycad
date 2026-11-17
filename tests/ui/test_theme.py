# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Regression checks for the professional workbench color system."""

from __future__ import annotations

from importlib import import_module, util
from typing import Literal, Protocol, cast

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.app import build_app
from mycad.ui.main_window import MainWindow

ThemeName = Literal["light", "dark"]


class _ThemeTokens(Protocol):
    canvas: str
    panel: str
    secondary_panel: str
    text: str
    secondary_text: str
    focus: str
    error: str
    error_background: str


class _ThemeApi(Protocol):
    LIGHT_THEME: _ThemeTokens

    def theme_tokens(self, theme: ThemeName) -> _ThemeTokens: ...

    def apply_theme(self, app: QApplication, theme: ThemeName) -> None: ...


def _theme_api() -> _ThemeApi:
    spec = util.find_spec("mycad.ui.theme")
    assert spec is not None, "the semantic theme module must be implemented"
    return cast(_ThemeApi, import_module("mycad.ui.theme"))


def _contrast_ratio(foreground: str, background: str) -> float:
    def luminance(value: str) -> float:
        color = QColor(value)
        channels = [color.redF(), color.greenF(), color.blueF()]
        linear = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first, second = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def test_default_application_palette_uses_bright_workbench_colors(qapp: QApplication) -> None:
    MainWindow()
    palette = qapp.palette()
    assert palette.color(QPalette.ColorRole.Window).name() == "#ffffff"
    assert palette.color(QPalette.ColorRole.Text).name() == "#243247"


def test_theme_updates_gl_canvas_together_with_widgets(qapp: QApplication) -> None:
    window = MainWindow(services=build_app(discoverers=[]))
    view = window.viewport
    assert view is not None
    window.act_theme_dark.trigger()
    assert tuple(view.opts["bgcolor"]) == QColor("#18212B").getRgbF()
    window.act_theme_light.trigger()
    assert tuple(view.opts["bgcolor"]) == QColor("#EFF3F7").getRgbF()


def test_theme_tokens_match_the_approved_bright_design(qapp: QApplication) -> None:
    theme = _theme_api()
    light = theme.LIGHT_THEME
    assert light.canvas == "#EFF3F7"
    assert light.panel == "#FFFFFF"
    assert light.secondary_panel == "#F7F9FB"
    assert light.text == "#243247"
    assert light.secondary_text == "#586B80"
    assert light.focus == "#255BCE"
    assert light.error == "#B13C42"
    assert light.error_background == "#FFF0EF"
    for tokens in (light, theme.theme_tokens("dark")):
        assert _contrast_ratio(tokens.text, tokens.panel) >= 4.5
        assert _contrast_ratio(tokens.secondary_text, tokens.panel) >= 4.5


def test_applying_dark_theme_updates_an_existing_widget_palette(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLabel

    theme = _theme_api()
    label = QLabel("Theme sample")
    theme.apply_theme(qapp, "dark")
    assert label.palette().color(QPalette.ColorRole.Window).name() == "#202833"
    assert label.palette().color(QPalette.ColorRole.Text).name() == "#e6edf5"
    theme.apply_theme(qapp, "light")


def test_dark_theme_updates_drawing_canvas_and_preserves_layer_color(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    window = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    window._apply_theme_setting("light", persist=False)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    line = LineEntity(uuid4().hex, (-20, 10), (20, 10))
    assert canvas.replace_draft_entities((line,))
    bg = canvas.local_to_screen((0, -10))
    stroke = canvas.local_to_screen((10, 10))
    light = canvas.grab().toImage()
    assert light.pixelColor(bg).lightness() > 200
    assert light.pixelColor(stroke).lightness() < 120
    window._apply_theme_setting("dark", persist=False)
    dark = canvas.grab().toImage()
    assert dark.pixelColor(bg).lightness() < 60
    assert dark.pixelColor(stroke).lightness() > 160
    assert canvas.layer_table.get(line.layer_name).color_rgb == (40, 46, 52)
    window._apply_theme_setting("light", persist=False)
    assert canvas.grab().toImage().pixelColor(bg).lightness() > 200


def test_dark_theme_is_applied_to_new_drawing(qtbot: QtBot) -> None:
    window = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.show()
    window._apply_theme_setting("dark", persist=False)
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.canvas.set_grid_visible(False)
    image = editor.canvas.grab().toImage()
    assert image.pixelColor(editor.canvas.local_to_screen((0, -10))).lightness() < 60
    window._apply_theme_setting("light", persist=False)


def test_dark_theme_follows_drawing_document_switches(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window._apply_theme_setting("light", persist=False)
    first = window.new_session_document("sketch")
    editor_a = window.active_sketch_dialog()
    assert editor_a is not None
    second = window.new_session_document("sketch")
    editor_b = window.active_sketch_dialog()
    assert editor_b is not None and editor_b is not editor_a
    window._apply_theme_setting("dark", persist=False)
    window.activate_session_document(first.loaded.document.document_id)
    current = window.active_sketch_dialog()
    assert current is not None
    current.canvas.set_grid_visible(False)
    assert (
        current.canvas.grab()
        .toImage()
        .pixelColor(current.canvas.local_to_screen((0, -10)))
        .lightness()
        < 60
    )
    window.activate_session_document(second.loaded.document.document_id)
    current = window.active_sketch_dialog()
    assert current is not None
    current.canvas.set_grid_visible(False)
    assert (
        current.canvas.grab()
        .toImage()
        .pixelColor(current.canvas.local_to_screen((0, -10)))
        .lightness()
        < 60
    )
    window._apply_theme_setting("light", persist=False)


def test_dark_drawing_keeps_dimensions_and_crosshair_visible(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(700, 500)
    canvas.set_grid_visible(False)
    line = LineEntity(uuid4().hex, (-30, 0), (30, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        60,
        "mm",
        driving=False,
        position_mm=(0, 20),
    )
    canvas.entities = [line]
    canvas.constraints = [dimension]
    canvas.set_drawing_theme("dark")
    canvas.show()
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    rect = canvas.dimension_label_rect(dimension, layout.label)
    QTest.mouseMove(canvas, QPoint(100, 100))
    image = canvas.grab().toImage()
    assert image.pixelColor(QPoint(100, 100)).lightness() > 150
    assert image.pixelColor(QPoint(int(rect.left() + 2), int(rect.top() + 2))).lightness() < 80
    color = canvas._drawing_color(QColor(*canvas.annotation_layer(dimension).color_rgb))
    assert color.lightness() > QColor("#202830").lightness() + 50


def test_start_page_cards_follow_theme_with_readable_enabled_and_disabled_text(
    qtbot: QtBot,
) -> None:
    from PySide6.QtCore import QPoint

    window = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.resize(1100, 750)
    window.show()
    window.show_start_page()
    page = window.start_page
    for name, expected_bg, expected_text, disabled_bg, disabled_text in (
        ("dark", "#202833", "#e6edf5", "#27323f", "#a9b7c7"),
        ("light", "#ffffff", "#243247", "#f7f9fb", "#586b80"),
    ):
        window._apply_theme_setting(name, persist=False)
        for card in (page.drawing_button, page.engineering_button, page.part_button):
            assert card.grab().toImage().pixelColor(QPoint(10, 10)).name() == expected_bg
            assert f"color: {expected_text}" in card.styleSheet().lower()
            assert _contrast_ratio(expected_text, expected_bg) >= 4.5
        card = page.assembly_button
        assert not card.isEnabled()
        assert card.grab().toImage().pixelColor(QPoint(10, 10)).name() == disabled_bg
        assert f"color: {disabled_text}" in card.styleSheet().lower()
        assert _contrast_ratio(disabled_text, disabled_bg) >= 4.5
