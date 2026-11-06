# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Template selection, title fields and explicit DXF import preview."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QStandardPaths, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mycad.core.drawing import DrawingSheet, DrawingState
from mycad.core.drawing_projection import build_drawing_scene
from mycad.core.drawing_templates import DrawingTemplate, TemplateText, builtin_template
from mycad.formats.drawing_templates import TemplateLibrary, dxf_layouts, import_dxf_template
from mycad.ui.drawing_canvas import DrawingCanvas


class DrawingTemplateChoiceDialog(QDialog):
    """Choose a built-in sheet template before allocating a document."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("drawingTemplateDialog")
        self.setWindowTitle("选择工程图模板")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("选择图纸模板；模型来源可稍后选择。"))
        self.selector = QComboBox()
        for label, value in (
            ("GB 国标机械图", "GB"),
            ("ISO 机械图", "ISO"),
            ("原有简单图框", "legacy"),
        ):
            self.selector.addItem(label, value)
        layout.addWidget(self.selector)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def _spin(value: float, minimum: float = 10, maximum: float = 10000) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(3)
    spin.setValue(value)
    return spin


def _show_template(
    canvas: DrawingCanvas, template: DrawingTemplate, values: tuple[tuple[str, str], ...] = ()
) -> None:
    sheet = DrawingSheet(uuid4(), size_mm=template.size_mm, template=template, title=values)
    canvas.set_scene(build_drawing_scene(DrawingState(sheets=(sheet,)), sheet.sheet_id, {}))


class TemplateImportDialog(QDialog):
    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("导入工程图模板 · DXF")
        self.resize(1000, 760)
        self.path = path
        self.template: DrawingTemplate | None = None
        outer = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(path.stem)
        self.standard = QLineEdit("自定义 / 导入 DXF")
        self.layout_choice = QComboBox()
        self.layout_choice.addItems(list(dxf_layouts(path)))
        self.unit = QComboBox()
        for label, value in (
            ("按文件单位", ""),
            ("毫米", "mm"),
            ("英寸", "inch"),
            ("厘米", "cm"),
            ("米", "m"),
        ):
            self.unit.addItem(label, value)
        self.paper_width, self.paper_height = _spin(297), _spin(210)
        self.offset_x, self.offset_y = _spin(0, -100000, 100000), _spin(0, -100000, 100000)
        for label, widget in (
            ("模板名称", self.name),
            ("标准 / 企业", self.standard),
            ("源布局", self.layout_choice),
            ("源单位", self.unit),
            ("幅面宽 mm", self.paper_width),
            ("幅面高 mm", self.paper_height),
            ("原点偏移 X mm", self.offset_x),
            ("原点偏移 Y mm", self.offset_y),
        ):
            form.addRow(label, widget)
        top = QHBoxLayout()
        top.addLayout(form)
        self.canvas = DrawingCanvas()
        top.addWidget(self.canvas, 1)
        outer.addLayout(top, 1)
        self.mapping = QTableWidget(0, 2)
        self.mapping.setHorizontalHeaderLabels(["文字 / 属性默认值", "绑定字段（留空为固定文字）"])
        self.mapping.horizontalHeader().setStretchLastSection(True)
        self.mapping.setMaximumHeight(190)
        outer.addWidget(self.mapping)
        self.message = QLabel("先检查源布局、单位和幅面，再生成预览；所有坐标按纸面毫米保存。")
        self.message.setWordWrap(True)
        outer.addWidget(self.message)
        preview = QPushButton("生成预览")
        preview.clicked.connect(self.preview)
        outer.addWidget(preview)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存到模板库")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        self.buttons.accepted.connect(self._accept_template)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        for combo in (self.unit, self.layout_choice):
            combo.currentIndexChanged.connect(self._invalidate)
        for spin in (self.paper_width, self.paper_height, self.offset_x, self.offset_y):
            spin.valueChanged.connect(self._invalidate)
        self.mapping.itemChanged.connect(self._mapping_changed)

    def _invalidate(self) -> None:
        self.template = None
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        self.message.setText("设置已改变，请重新生成预览。")

    def preview(self) -> None:
        try:
            template = import_dxf_template(
                self.path,
                name=self.name.text().strip(),
                size_mm=(self.paper_width.value(), self.paper_height.value()),
                layout=self.layout_choice.currentText(),
                unit=str(self.unit.currentData()) or None,
                offset_mm=(self.offset_x.value(), self.offset_y.value()),
            )
            self.template = replace(template, standard=self.standard.text().strip())
            self.mapping.blockSignals(True)
            self.mapping.setRowCount(len(template.texts))
            for row, item in enumerate(template.texts):
                self.mapping.setItem(row, 0, QTableWidgetItem(item.text))
                self.mapping.setItem(row, 1, QTableWidgetItem(item.field))
            self.mapping.blockSignals(False)
            _show_template(self.canvas, self.template)
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(True)
            self.message.setText(
                f"预览成功：{len(template.curves)} 条曲线、{len(template.texts)} 处文字。可填写字段名，或修改默认文字。图线使用 MyCAD 图框线样式。"
            )
        except (OSError, ValueError, RuntimeError) as error:
            self._invalidate()
            self.message.setText(str(error))

    def _mapping_changed(self) -> None:
        if self.template is None:
            return
        try:
            texts: list[TemplateText] = []
            for row, item in enumerate(self.template.texts):
                value, field = self.mapping.item(row, 0), self.mapping.item(row, 1)
                if value is None or field is None:
                    return
                texts.append(replace(item, text=value.text(), field=field.text().strip()))
            self.template = replace(self.template, texts=tuple(texts))
            _show_template(self.canvas, self.template)
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(True)
        except ValueError as error:
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
            self.message.setText(str(error))

    def _accept_template(self) -> None:
        if self.template is None:
            return
        try:
            self.template = replace(
                self.template, name=self.name.text().strip(), standard=self.standard.text().strip()
            )
        except ValueError as error:
            self.message.setText(str(error))
            return
        self.accept()


class DrawingTemplatePanel(QWidget):
    selection_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        directory = (
            Path(
                QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
            )
            / "MyCAD"
            / "drawing-templates"
        )
        self.library = TemplateLibrary(directory)
        self.imported: dict[str, DrawingTemplate] = {}
        self._values: dict[str, str] = {}
        self.fields: dict[str, QLineEdit] = {}
        outer = QVBoxLayout(self)
        self.selector = QComboBox()
        for label, value in (
            ("GB 国标机械图", "GB"),
            ("ISO 机械图", "ISO"),
            ("原有简单图框", "legacy"),
        ):
            self.selector.addItem(label, value)
        outer.addWidget(self.selector)
        self.description = QLabel()
        self.description.setWordWrap(True)
        outer.addWidget(self.description)
        self.import_button = QPushButton("导入 DXF 模板…")
        self.import_button.clicked.connect(self.choose_import)
        outer.addWidget(self.import_button)
        self.preview_button = QPushButton("预览模板…")
        outer.addWidget(self.preview_button)
        self.field_form = QFormLayout()
        outer.addLayout(self.field_form)
        templates, issues = self.library.load()
        for template in templates:
            self.add_template(template)
        self.selector.currentIndexChanged.connect(self._changed)
        self._changed()
        if issues:
            self.description.setText("模板库部分文件未加载：\n" + "\n".join(issues))

    def add_template(self, template: DrawingTemplate) -> None:
        self.imported[template.template_id] = template
        index = self.selector.findData(template.template_id)
        if index == -1:
            self.selector.addItem(template.name, template.template_id)
        else:
            self.selector.setItemText(index, template.name)

    def values(self) -> dict[str, str]:
        self._values.update({key: edit.text() for key, edit in self.fields.items()})
        return dict(self._values)

    def _changed(self) -> None:
        self.values()
        while self.field_form.rowCount():
            self.field_form.removeRow(0)
        self.fields.clear()
        selected = str(self.selector.currentData())
        template = self.imported.get(selected)
        fields = {
            t.field: t.text for t in (template or builtin_template("GB", "A4")).texts if t.field
        }
        self.description.setText(
            f"{template.standard}\n幅面 {template.size_mm[0]:g} × {template.size_mm[1]:g} mm"
            if template
            else (
                "原样保留旧图框"
                if selected == "legacy"
                else builtin_template(selected, "A4").standard
            )
        )
        if selected == "legacy":
            fields = {}
        for key, default in fields.items():
            if key == "标题":
                continue
            edit = QLineEdit(self._values.get(key, default))
            if key in ("比例", "页码"):
                edit.setPlaceholderText("留空自动填写")
            self.fields[key] = edit
            self.field_form.addRow(key, edit)
        self.selection_changed.emit()

    def template_for(self, paper: str, landscape: bool, angle: str) -> DrawingTemplate | None:
        selected = str(self.selector.currentData())
        if selected == "legacy":
            return None
        if selected in ("GB", "ISO"):
            return builtin_template(selected, paper, landscape=landscape, projection_angle=angle)
        return self.imported[selected]

    def load_sheet(self, sheet: DrawingSheet) -> None:
        self._values = dict(sheet.title)
        self.fields.clear()
        template = sheet.template
        selected = "legacy"
        if template is not None:
            if template.template_id.startswith("builtin:"):
                selected = template.template_id.split(":")[1]
            else:
                self.add_template(template)
                selected = template.template_id
        self.selector.blockSignals(True)
        self.selector.setCurrentIndex(self.selector.findData(selected))
        self.selector.blockSignals(False)
        self._changed()

    def choose_import(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "导入工程图模板", "", "DXF 图纸 (*.dxf)")
        if not filename:
            return
        try:
            dialog = TemplateImportDialog(Path(filename), self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.template is not None:
                self.library.save(dialog.template)
                self.add_template(dialog.template)
                self.selector.setCurrentIndex(self.selector.findData(dialog.template.template_id))
        except (OSError, ValueError, RuntimeError) as error:
            self.description.setText(f"导入失败：{error}")

    def show_preview(self, template: DrawingTemplate, values: tuple[tuple[str, str], ...]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"模板预览 · {template.name}")
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        canvas = DrawingCanvas()
        layout.addWidget(canvas)
        _show_template(canvas, template, values)
        dialog.exec()
