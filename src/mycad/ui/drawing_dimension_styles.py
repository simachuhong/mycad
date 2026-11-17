# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Stage edits to named styles belonging to one drawing."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.sketch_layers import STANDARD_LINEWEIGHTS_MM
from mycad.ui.dimension_colors import dimension_color_combo


class DrawingDimensionStylesDialog(QDialog):
    """Build a new table without mutating the source drawing on cancel."""

    def __init__(
        self,
        table: DimensionStyleTable,
        used_names: frozenset[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("图纸标注样式")
        self._styles = {style.name.casefold(): style for style in table.styles}
        self._current = table.current_name
        self._used = {name.casefold() for name in used_names}
        root = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setObjectName("dimensionStyleScroll")
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        root.addWidget(scroll)
        layout.addWidget(QLabel("样式保存在当前图纸；修改后更新关联尺寸。"))
        self.current_label = QLabel()
        layout.addWidget(self.current_label)
        form = QFormLayout()
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.name.addItems([style.name for style in table.styles])
        self.name.setCurrentText(table.current_name)
        form.addRow("样式名称", self.name)
        self.precision = QSpinBox()
        self.precision.setRange(0, 8)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.1, 100)
        form.addRow("小数位数", self.precision)
        form.addRow("标注比例", self.scale)
        self.arrow_first = QComboBox()
        self.arrow_second = QComboBox()
        for combo in (self.arrow_first, self.arrow_second):
            for label, value in (
                ("开口", "open"),
                ("闭合", "closed"),
                ("实心闭合", "filled"),
                ("斜线", "tick"),
                ("无", "none"),
            ):
                combo.addItem(label, value)
        self.arrow_first.currentIndexChanged.connect(self.arrow_second.setCurrentIndex)
        form.addRow("第一箭头", self.arrow_first)
        form.addRow("第二箭头", self.arrow_second)
        self.arrow_size = QDoubleSpinBox()
        self.arrow_size.setRange(0.01, 10000)
        self.dimline_extension = QDoubleSpinBox()
        self.extline_extension = QDoubleSpinBox()
        self.extline_offset = QDoubleSpinBox()
        self.text_height = QDoubleSpinBox()
        self.text_height.setRange(0.01, 10000)
        for field in (self.dimline_extension, self.extline_extension, self.extline_offset):
            field.setRange(0, 10000)
        form.addRow("箭头大小 (mm)", self.arrow_size)
        form.addRow("尺寸线超出标记 (mm)", self.dimline_extension)
        form.addRow("尺寸界线超出尺寸线 (mm)", self.extline_extension)
        form.addRow("尺寸界线起点偏移 (mm)", self.extline_offset)
        form.addRow("文字高度 (mm)", self.text_height)
        self.center_mark = QComboBox()
        for label, value in (("无", "none"), ("中心标记", "mark"), ("中心线", "line")):
            self.center_mark.addItem(label, value)
        self.center_size = QDoubleSpinBox()
        self.center_size.setRange(0.01, 10000)
        form.addRow("圆心标记", self.center_mark)
        form.addRow("圆心标记大小 (mm)", self.center_size)
        self.dimension_color = dimension_color_combo()
        self.extension_color = dimension_color_combo()
        self.text_color = dimension_color_combo()
        form.addRow("尺寸线和箭头颜色", self.dimension_color)
        form.addRow("界线和圆心标记颜色", self.extension_color)
        form.addRow("文字颜色", self.text_color)
        self.dimension_lineweight = QComboBox()
        self.extension_lineweight = QComboBox()
        for combo in (self.dimension_lineweight, self.extension_lineweight):
            combo.addItem("随图层", -1)
            for width in STANDARD_LINEWEIGHTS_MM:
                combo.addItem(f"{width:.2f} mm", round(width * 100))
        form.addRow("尺寸线线宽", self.dimension_lineweight)
        form.addRow("尺寸界线线宽", self.extension_lineweight)
        self.dimension_linetype = QComboBox()
        self.extension_linetype_first = QComboBox()
        self.extension_linetype_second = QComboBox()
        for combo in (
            self.dimension_linetype,
            self.extension_linetype_first,
            self.extension_linetype_second,
        ):
            for text, value in (
                ("随图层", "BYLAYER"),
                ("连续线", "CONTINUOUS"),
                ("虚线", "DASHED"),
                ("点线", "DOTTED"),
                ("点划线", "DASHDOT"),
            ):
                combo.addItem(text, value)
        form.addRow("尺寸线线型", self.dimension_linetype)
        form.addRow("第一界线线型", self.extension_linetype_first)
        form.addRow("第二界线线型", self.extension_linetype_second)
        self.suppress_extension_first = QCheckBox("隐藏第一界线")
        self.suppress_extension_second = QCheckBox("隐藏第二界线")
        form.addRow("尺寸界线显隐", self.suppress_extension_first)
        form.addRow("", self.suppress_extension_second)
        self.suppress_dimension_first = QCheckBox("隐藏第一尺寸线及箭头")
        self.suppress_dimension_second = QCheckBox("隐藏第二尺寸线及箭头")
        form.addRow("尺寸线显隐", self.suppress_dimension_first)
        form.addRow("", self.suppress_dimension_second)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.save_button = QPushButton("保存样式")
        self.set_current_button = QPushButton("设为当前")
        self.delete_button = QPushButton("删除样式")
        for button in (self.save_button, self.set_current_button, self.delete_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.local_presets_button = QPushButton("本机格式预设…")
        layout.addWidget(self.local_presets_button)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.name.currentTextChanged.connect(self._select)
        self.save_button.clicked.connect(self._save)
        self.set_current_button.clicked.connect(self._set_current)
        self.delete_button.clicked.connect(self._delete)
        self._select(table.current_name)
        self._update_current_label()

    @property
    def table(self) -> DimensionStyleTable:
        return DimensionStyleTable(tuple(self._styles.values()), self._current)

    def _update_current_label(self) -> None:
        self.current_label.setText(f"当前样式：{self._current}")

    def _select(self, name: str) -> None:
        style = self._styles.get(name.casefold())
        if style is not None:
            self.precision.setValue(style.precision)
            self.scale.setValue(style.scale)
            self.arrow_first.setCurrentIndex(self.arrow_first.findData(style.arrow_first))
            self.arrow_second.setCurrentIndex(self.arrow_second.findData(style.arrow_second))
            self.arrow_size.setValue(style.arrow_size)
            self.dimline_extension.setValue(style.dimline_extension)
            self.extline_extension.setValue(style.extline_extension)
            self.extline_offset.setValue(style.extline_offset)
            self.text_height.setValue(style.text_height)
            self.center_mark.setCurrentIndex(self.center_mark.findData(style.center_mark))
            self.center_size.setValue(style.center_size)
            self.dimension_color.setCurrentIndex(
                self.dimension_color.findData(style.dimension_color)
            )
            self.extension_color.setCurrentIndex(
                self.extension_color.findData(style.extension_color)
            )
            self.text_color.setCurrentIndex(self.text_color.findData(style.text_color))
            self.dimension_lineweight.setCurrentIndex(
                self.dimension_lineweight.findData(style.dimension_lineweight)
            )
            self.extension_lineweight.setCurrentIndex(
                self.extension_lineweight.findData(style.extension_lineweight)
            )
            self.dimension_linetype.setCurrentIndex(
                self.dimension_linetype.findData(style.dimension_linetype)
            )
            self.extension_linetype_first.setCurrentIndex(
                self.extension_linetype_first.findData(style.extension_linetype_first)
            )
            self.extension_linetype_second.setCurrentIndex(
                self.extension_linetype_second.findData(style.extension_linetype_second)
            )
            self.suppress_extension_first.setChecked(style.suppress_extension_first)
            self.suppress_extension_second.setChecked(style.suppress_extension_second)
            self.suppress_dimension_first.setChecked(style.suppress_dimension_first)
            self.suppress_dimension_second.setChecked(style.suppress_dimension_second)

    def _save(self) -> None:
        try:
            style = DimensionStyle(
                self.name.currentText(),
                self.precision.value(),
                self.scale.value(),
                str(self.arrow_first.currentData()),
                str(self.arrow_second.currentData()),
                self.arrow_size.value(),
                self.dimline_extension.value(),
                self.extline_extension.value(),
                self.extline_offset.value(),
                self.text_height.value(),
                str(self.center_mark.currentData()),
                self.center_size.value(),
                int(self.dimension_color.currentData()),
                int(self.extension_color.currentData()),
                int(self.text_color.currentData()),
                int(self.dimension_lineweight.currentData()),
                int(self.extension_lineweight.currentData()),
                str(self.dimension_linetype.currentData()),
                str(self.extension_linetype_first.currentData()),
                str(self.extension_linetype_second.currentData()),
                self.suppress_extension_first.isChecked(),
                self.suppress_extension_second.isChecked(),
                self.suppress_dimension_first.isChecked(),
                self.suppress_dimension_second.isChecked(),
            )
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        key = style.name.casefold()
        existing = self._styles.get(key)
        if existing is not None and existing.name != style.name:
            self.message.setText("样式名称与已有名称仅大小写不同。")
            return
        if existing is None and len(self._styles) >= 500:
            self.message.setText("每张图纸最多保存 500 个标注样式。")
            return
        self._styles[key] = style
        if existing is None:
            self.name.addItem(style.name)
        self.name.setCurrentText(style.name)
        self.message.setText("样式已暂存；点击确定应用。")

    def _set_current(self) -> None:
        style = self._styles.get(self.name.currentText().casefold())
        if style is None:
            self.message.setText("请先保存样式。")
            return
        self._current = style.name
        self._update_current_label()
        self.message.setText("当前样式已暂存；点击确定应用。")

    def _delete(self) -> None:
        style = self._styles.get(self.name.currentText().casefold())
        if style is None:
            self.message.setText("请选择已有样式。")
        elif style.name.casefold() == self._current.casefold():
            self.message.setText("当前样式不能删除，请先切换当前样式。")
        elif style.name.casefold() in self._used:
            self.message.setText("样式仍被尺寸使用，不能删除。")
        else:
            del self._styles[style.name.casefold()]
            self.name.removeItem(self.name.findText(style.name))
            self.message.setText("样式删除已暂存；点击确定应用。")
