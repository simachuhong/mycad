# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Application font resources, independent of drawing documents and styles."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from mycad.core.drawing_text import TextStyle
from mycad.ui.font_manager import FontManager


class FontResourcesDialog(QDialog):
    """Browse fonts and import persistent MyCAD-local font resources."""

    def __init__(
        self, parent: QWidget | None = None, *, manager: FontManager | None = None
    ) -> None:
        super().__init__(parent)
        self.manager = manager or FontManager()
        self.setWindowTitle("字体管理")
        self.resize(620, 370)
        layout = QFormLayout(self)
        self.persistence_notice = QLabel(
            "导入字体仅供 MyCAD 使用，不安装到操作系统。导入立即保存；"
            "关闭本窗口或取消系统设置不会撤销已导入的字体。",
            self,
        )
        self.persistence_notice.setWordWrap(True)
        layout.addRow(self.persistence_notice)
        self.font_family = QComboBox(self)
        self.font_family.setObjectName("fontResourceFamily")
        self.font_family.setMaxVisibleItems(20)
        self.font_family.addItems(list(self.manager.families()))
        layout.addRow("可用字体", self.font_family)
        self.sample = QLineEdit("中文字体示例 ABC abc 0123456789 ⌀ ±", self)
        self.sample.setObjectName("fontResourceSample")
        layout.addRow("预览文字", self.sample)
        self.preview = QLabel(self.sample.text(), self)
        self.preview.setObjectName("fontResourcePreview")
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(90)
        self.preview.setTextFormat(Qt.TextFormat.PlainText)
        layout.addRow("字体预览", self.preview)
        self.directory = QLineEdit(str(self.manager.directory), self)
        self.directory.setObjectName("fontResourceDirectory")
        self.directory.setReadOnly(True)
        self.directory.setToolTip(str(self.manager.directory))
        layout.addRow("MyCAD 字体目录", self.directory)
        self.import_button = QPushButton("导入字体文件…", self)
        self.import_button.setObjectName("fontResourceImport")
        self.import_button.setToolTip("支持 TrueType / OpenType 字体及字体集合（TTF、OTF、TTC）。")
        self.import_button.clicked.connect(self._import_font)
        layout.addRow(self.import_button)
        self.status = QLabel("", self)
        self.status.setObjectName("fontResourceStatus")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addRow(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.font_family.currentTextChanged.connect(self._update_preview)
        self.sample.textChanged.connect(self._update_preview)
        self._update_preview()

    def selected_style(self) -> TextStyle:
        """Describe the current sample without editing any document style."""
        return TextStyle(font_family=self.font_family.currentText())

    def _update_preview(self) -> None:
        font = self.manager.resolve(self.selected_style())
        font.setPointSizeF(18)
        self.preview.setFont(font)
        self.preview.setText(self.sample.text())

    def _import_font(self) -> None:
        filename, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "导入 MyCAD 字体",
            "",
            "字体文件 (*.ttf *.otf *.ttc *.TTF *.OTF *.TTC)",
        )
        if not filename:
            return
        try:
            families = self.manager.import_font(Path(filename))
        except (OSError, ValueError) as exc:
            self.status.setText(f"导入失败：{exc}")
            return
        self.font_family.clear()
        self.font_family.addItems(list(self.manager.families()))
        if families:
            self.font_family.setCurrentText(families[0])
        self.status.setText(f"已导入：{'、'.join(families)}。字体已保存，可在文字样式中选择。")
        self._update_preview()
