# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Choose a supported document kind before creating a document."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mycad.core.document_kinds import DocumentType
from mycad.ui.cad_icons import set_button_icon


class NewDocumentDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, initial: DocumentType = "part") -> None:
        super().__init__(parent)
        self.setWindowTitle("新建文档")
        self.setMinimumWidth(570)
        self.setStyleSheet(
            "QToolButton { border: 1px solid transparent; border-radius: 6px; }"
            "QToolButton:checked { border: 2px solid palette(highlight); "
            "background: palette(alternate-base); }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.addWidget(QLabel("选择文档类型"))
        cards = QHBoxLayout()
        self.type_group = QButtonGroup(self)
        self.type_group.setExclusive(True)
        self.drawing_button = self._card("二维图", "sketch", "线、圆、图层与尺寸标注", 0)
        self.part_button = self._card("三维零件", "box", "草图、参数化特征与实体建模", 1)
        self.assembly_button = self._card(
            "装配体（规划中）", "group", "Assembly：未来用于零件装配", 2
        )
        self.assembly_button.setEnabled(False)
        for button in (self.drawing_button, self.part_button, self.assembly_button):
            cards.addWidget(button)
        root.addLayout(cards)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setMinimumHeight(56)
        root.addWidget(self.description)
        actions = QHBoxLayout()
        actions.addStretch()
        self.create_button = QPushButton("创建")
        self.create_button.setDefault(True)
        self.cancel_button = QPushButton("取消")
        actions.addWidget(self.create_button)
        actions.addWidget(self.cancel_button)
        root.addLayout(actions)
        self.create_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.type_group.idClicked.connect(self._show_description)
        (self.drawing_button if initial == "drawing2d" else self.part_button).setChecked(True)
        self._show_description()

    def _card(self, label: str, icon: str, tooltip: str, identity: int) -> QToolButton:
        button = QToolButton()
        button.setText(label)
        button.setToolTip(tooltip)
        button.setCheckable(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        set_button_icon(button, icon)
        button.setIconSize(QSize(42, 42))
        button.setMinimumSize(165, 108)
        self.type_group.addButton(button, identity)
        return button

    @property
    def document_type(self) -> DocumentType:
        return "drawing2d" if self.type_group.checkedId() == 0 else "part"

    def _show_description(self, _identity: int = 0) -> None:
        self.description.setText(
            "二维图：进入二维绘图工作区，使用图层、几何工具和尺寸标注。"
            if self.document_type == "drawing2d"
            else "三维零件：进入三维工作区，从草图或基本实体开始建模。"
        )
