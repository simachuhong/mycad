# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Semantic light/dark palettes and focusable Qt widget styling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ThemeName = Literal["light", "dark"]


@dataclass(frozen=True, slots=True)
class ThemeTokens:
    canvas: str
    panel: str
    secondary_panel: str
    divider: str
    text: str
    secondary_text: str
    focus: str
    active: str
    selection: str
    success: str
    success_background: str
    warning: str
    warning_background: str
    error: str
    error_background: str


LIGHT_THEME = ThemeTokens(
    canvas="#EFF3F7",
    panel="#FFFFFF",
    secondary_panel="#F7F9FB",
    divider="#DCE3EB",
    text="#243247",
    secondary_text="#586B80",
    focus="#255BCE",
    active="#EAF1FF",
    selection="#D98A22",
    success="#17735A",
    success_background="#EAF6F0",
    warning="#9D5A06",
    warning_background="#FFF4DD",
    error="#B13C42",
    error_background="#FFF0EF",
)

DARK_THEME = ThemeTokens(
    canvas="#18212B",
    panel="#202833",
    secondary_panel="#27323F",
    divider="#3A4757",
    text="#E6EDF5",
    secondary_text="#A9B7C7",
    focus="#86A9FF",
    active="#2E4364",
    selection="#F3AD4F",
    success="#54C49A",
    success_background="#1E3A33",
    warning="#FFC66D",
    warning_background="#453722",
    error="#FF8C8C",
    error_background="#4A282B",
)

_THEMES: dict[ThemeName, ThemeTokens] = {"light": LIGHT_THEME, "dark": DARK_THEME}


def theme_tokens(theme: ThemeName) -> ThemeTokens:
    """Return the immutable semantic palette for one supported theme."""
    return _THEMES[theme]


def apply_theme(app: QApplication, theme: ThemeName) -> None:
    """Apply a semantic palette and accessible focus/disabled/error styling."""
    tokens = theme_tokens(theme)
    palette = QPalette(app.palette())
    for role, color in (
        (QPalette.ColorRole.Window, tokens.panel),
        (QPalette.ColorRole.WindowText, tokens.text),
        (QPalette.ColorRole.Base, tokens.panel),
        (QPalette.ColorRole.AlternateBase, tokens.secondary_panel),
        (QPalette.ColorRole.Text, tokens.text),
        (QPalette.ColorRole.Button, tokens.panel),
        (QPalette.ColorRole.ButtonText, tokens.text),
        (QPalette.ColorRole.ToolTipBase, tokens.text),
        (QPalette.ColorRole.ToolTipText, tokens.panel),
        (QPalette.ColorRole.Highlight, tokens.focus),
        (QPalette.ColorRole.HighlightedText, tokens.panel),
        (QPalette.ColorRole.Link, tokens.focus),
        (QPalette.ColorRole.Mid, tokens.divider),
        (QPalette.ColorRole.Midlight, tokens.secondary_panel),
        (QPalette.ColorRole.BrightText, tokens.error),
        (QPalette.ColorRole.PlaceholderText, tokens.secondary_text),
    ):
        palette.setColor(role, QColor(color))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(tokens.secondary_text),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(tokens.secondary_text),
    )
    app.setStyleSheet(
        f"""
        QWidget {{ color: {tokens.text}; font-family: "Noto Sans CJK SC", "Noto Sans", sans-serif; font-size: 13px; }}
        QMainWindow, QDialog, QDockWidget {{ background: {tokens.panel}; }}
        QToolBar {{ background: {tokens.secondary_panel}; border: 0; border-bottom: 1px solid {tokens.divider}; spacing: 4px; padding: 4px; }}
        QToolButton, QPushButton {{ border: 1px solid transparent; border-radius: 4px; padding: 5px 7px; }}
        QToolButton:hover, QPushButton:hover {{ background: {tokens.active}; border-color: {tokens.divider}; }}
        QPushButton[sketchTool="true"]:checked {{ background: {tokens.active}; border-color: {tokens.focus}; }}
        QToolButton:focus, QPushButton:focus, QLineEdit:focus, QComboBox:focus,
        QSpinBox:focus, QDoubleSpinBox:focus, QTabBar::tab:focus,
        QTreeView:focus, QTableView:focus {{ border: 1px solid {tokens.focus}; }}
        QToolButton:disabled, QPushButton:disabled {{ color: {tokens.secondary_text}; background: {tokens.secondary_panel}; }}
        QDockWidget::title {{ background: {tokens.secondary_panel}; border-bottom: 1px solid {tokens.divider}; padding: 6px 8px; font-weight: 600; }}
        QTabWidget::pane {{ border: 1px solid {tokens.divider}; }}
        QTabBar::tab {{ background: {tokens.secondary_panel}; border: 1px solid {tokens.divider}; padding: 6px 10px; }}
        QTabBar::tab:selected {{ background: {tokens.active}; border-bottom: 2px solid {tokens.focus}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{ background: {tokens.panel}; border: 1px solid {tokens.divider}; border-radius: 3px; padding: 4px; selection-background-color: {tokens.focus}; }}
        QTreeView::item:selected, QTableView::item:selected {{ background: {tokens.active}; color: {tokens.text}; }}
        QStatusBar {{ background: {tokens.secondary_panel}; border-top: 1px solid {tokens.divider}; }}
        QLabel#statusError, QMessageBox#errorMessage QLabel#qt_msgbox_label {{ color: {tokens.error}; background: {tokens.error_background}; }}
        QToolTip {{ color: {tokens.panel}; background: {tokens.text}; border: 1px solid {tokens.divider}; padding: 3px; }}
        """
    )
    app.setPalette(palette)
    for widget in app.allWidgets():
        widget.setPalette(palette)
