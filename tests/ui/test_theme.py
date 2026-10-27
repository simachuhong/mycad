# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Regression checks for the professional workbench color system."""

from __future__ import annotations

from importlib import import_module, util
from typing import Literal, Protocol, cast

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

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
