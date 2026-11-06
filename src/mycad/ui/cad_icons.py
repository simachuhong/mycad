# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Owned CAD glyphs with consistent geometry and explicit theme/state palettes."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from typing import override

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QApplication, QTreeWidget, QTreeWidgetItem, QWidget

from mycad.ui.theme import ThemeName

ICON_NAMES = (
    "draw-select",
    "draw-point",
    "draw-line",
    "draw-polyline",
    "draw-rectangle",
    "draw-polygon",
    "draw-circle",
    "draw-arc",
    "draw-spline",
    "draw-trim",
    "draw-extend",
    "draw-split",
    "edit-move",
    "edit-copy",
    "edit-rotate",
    "edit-mirror",
    "edit-offset",
    "edit-linear_array",
    "edit-circular_array",
    "dimension",
    "dim-smart",
    "dim-horizontal",
    "dim-vertical",
    "dim-aligned",
    "dim-angle",
    "dim-radius",
    "dim-diameter",
    "dim-arc_length",
    "dim-continue",
    "dim-baseline",
    "dim-ordinate",
    "layers",
    "appearance",
    "axes",
    "boolean-cut",
    "boolean-intersect",
    "box",
    "camera",
    "cancel",
    "confirm",
    "console",
    "current-model",
    "cylinder",
    "dark",
    "datum",
    "delete",
    "document",
    "edge",
    "exit",
    "export",
    "extrude",
    "face",
    "features",
    "fillet",
    "filter",
    "fit",
    "grid",
    "group",
    "hole",
    "hole-pattern",
    "import",
    "info",
    "keyboard",
    "layout",
    "license",
    "light",
    "lock",
    "measure",
    "mesh",
    "modify",
    "new",
    "open",
    "orthographic",
    "panel-bottom",
    "panel-left",
    "panel-right",
    "panel-top",
    "perspective",
    "plan",
    "plugin",
    "rebuild",
    "redo",
    "reference",
    "revolve",
    "save",
    "save-as",
    "settings",
    "shaded",
    "shaded-edges",
    "sketch",
    "sphere",
    "undo",
    "units",
    "vertex",
    "view-back",
    "view-bottom",
    "view-front",
    "view-isometric",
    "view-left",
    "view-right",
    "view-top",
    "wireframe",
)


@lru_cache(maxsize=32)
def _source(name: str) -> str:
    if name not in ICON_NAMES:
        raise ValueError(f"Unknown CAD icon: {name}")
    return files("mycad.ui").joinpath("icons", f"{name}.svg").read_text(encoding="utf-8")


def _colored_svg(name: str, theme: ThemeName, disabled: bool) -> QByteArray:
    source = _source(name)
    if disabled:
        colors = (
            ("#8E9AA8", "#8E9AA8", "#EBEFF3", "#E1E7EE", "#F7F9FB")
            if theme == "light"
            else ("#657587", "#657587", "#293440", "#334150", "#202833")
        )
    else:
        colors = (
            ("#33465B", "#2563A6", "#E6EDF4", "#CCE1F5", "#FFFFFF")
            if theme == "light"
            else ("#D4DFEB", "#83BFFF", "#344355", "#264D73", "#202833")
        )
    for original, color in zip(
        ("#33465B", "#2563A6", "#E6EDF4", "#CCE1F5", "#FFFFFF"), colors, strict=True
    ):
        source = source.replace(original, color)
    return QByteArray(source.encode("utf-8"))


class _CadIconEngine(QIconEngine):
    def __init__(self, name: str, theme: ThemeName) -> None:
        super().__init__()
        self._name = name
        self._theme: ThemeName = theme
        self._normal = QSvgRenderer(_colored_svg(name, theme, False))
        self._disabled = QSvgRenderer(_colored_svg(name, theme, True))

    @override
    def clone(self) -> QIconEngine:
        return _CadIconEngine(self._name, self._theme)

    @override
    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        renderer = self._disabled if mode == QIcon.Mode.Disabled else self._normal
        side = min(rect.width(), rect.height())
        bounds = QRectF(
            rect.x() + (rect.width() - side) / 2, rect.y() + (rect.height() - side) / 2, side, side
        )
        painter.save()
        renderer.render(painter, bounds)
        painter.restore()

    @override
    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        result = QPixmap(size)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return result


def cad_icon(name: str, theme: ThemeName = "light") -> QIcon:
    """Render original SVG geometry at Qt's requested display resolution."""
    return QIcon(_CadIconEngine(name, theme))


COMMAND_ICONS: dict[str, str] = {
    "drawing.layers.set": "layers",
    "feature.box": "box",
    "feature.cylinder": "cylinder",
    "feature.sphere": "sphere",
    "feature.extrude": "extrude",
    "feature.revolve": "revolve",
    "feature.hole": "hole",
    "feature.hole_pattern": "hole-pattern",
    "modify.fillet": "fillet",
    "modify.boolean_cut": "boolean-cut",
    "modify.boolean_intersect": "boolean-intersect",
    "modify.boolean_bodies": "boolean-intersect",
    "modify.body_transform": "modify",
    "modify.body_pattern": "hole-pattern",
}
CATEGORY_ICONS = {"drawing": "layers", "feature": "features", "modify": "modify"}
STRUCTURE_ICONS = {"基准": "datum", "草图": "sketch", "特征": "features", "实体": "box"}
ICON_ROLE = int(Qt.ItemDataRole.UserRole) + 21


def command_icon_name(command_id: str) -> str:
    """Unknown extension commands get a neutral plugin glyph, never a guessed feature."""
    return COMMAND_ICONS.get(command_id, "plugin")


def set_tree_icon(item: QTreeWidgetItem, name: str, theme: ThemeName) -> None:
    item.setData(0, ICON_ROLE, name)
    item.setIcon(0, cad_icon(name, theme))


def refresh_tree_icons(tree: QTreeWidget, theme: ThemeName) -> None:
    """Recolor in place without rebuilding nodes or disturbing selection/expansion."""
    pending = [tree.invisibleRootItem()]
    while pending:
        item = pending.pop()
        name = item.data(0, ICON_ROLE)
        if isinstance(name, str):
            item.setIcon(0, cad_icon(name, theme))
        for index in range(item.childCount()):
            child = item.child(index)
            if child is not None:
                pending.append(child)


def current_icon_theme() -> ThemeName:
    return "dark" if QApplication.palette().window().color().lightness() < 128 else "light"


def set_button_icon(button: QAbstractButton, name: str) -> None:
    button.setProperty("cadIconName", name)
    button.setIcon(cad_icon(name, current_icon_theme()))
    button.setIconSize(QSize(18, 18))


def refresh_button_icons(root: QWidget, theme: ThemeName) -> None:
    for button in root.findChildren(QAbstractButton):
        name = button.property("cadIconName")
        if isinstance(name, str):
            button.setIcon(cad_icon(name, theme))
