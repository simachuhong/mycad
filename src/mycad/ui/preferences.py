# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Application preferences for the independent drawing workspace."""

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPushButton,
    QWidget,
)

from mycad.ui.font_resources import FontResourcesDialog

CURSOR_STYLE_KEY = "drawing2d/cursorStyle"
CONSTRAINT_MARKERS_KEY = "drawing2d/constraintMarkersVisible"
DATUM_SYMBOL_STYLE_KEY = "drawing2d/defaultDatumSymbolStyle"


def default_datum_symbol_style(settings: QSettings) -> str:
    value = settings.value(DATUM_SYMBOL_STYLE_KEY, "rectangle")
    return value if value in ("rectangle", "circle") else "rectangle"


def drawing_cursor_style(settings: QSettings) -> str:
    value = settings.value(CURSOR_STYLE_KEY, "short")
    return value if value in ("short", "full") else "short"


def drawing_constraint_markers_visible(settings: QSettings) -> bool:
    return bool(settings.value(CONSTRAINT_MARKERS_KEY, True, type=bool))


class CursorSettingsDialog(QDialog):
    """Let the user choose the shape of the independent 2D cursor."""

    def __init__(
        self, style: str, parent: QWidget | None = None, *, markers_visible: bool = True
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("系统设置")
        layout = QFormLayout(self)
        self.cursor_style = QComboBox(self)
        self.cursor_style.setObjectName("drawingCursorStyle")
        self.cursor_style.addItem("短十字光标", "short")
        self.cursor_style.addItem("贯穿画布的十字线", "full")
        self.cursor_style.setCurrentIndex(1 if style == "full" else 0)
        layout.addRow("二维工作区光标", self.cursor_style)
        self.constraint_markers = QCheckBox("显示几何约束标记", self)
        self.constraint_markers.setObjectName("drawingConstraintMarkersVisible")
        self.constraint_markers.setChecked(markers_visible)
        self.constraint_markers.setToolTip("控制重合、水平、垂直等几何约束符号的显示。")
        layout.addRow("二维工作区", self.constraint_markers)
        self.font_resources = QPushButton("字体管理…", self)
        self.font_resources.setObjectName("fontResourcesButton")
        self.font_resources.clicked.connect(self._open_font_resources)
        layout.addRow("应用字体", self.font_resources)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def selected_style(self) -> str:
        return "full" if self.cursor_style.currentData() == "full" else "short"

    def _open_font_resources(self) -> None:
        FontResourcesDialog(self).exec()
