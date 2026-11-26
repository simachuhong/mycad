# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Structured editor for independent geometric tolerance rows."""

from __future__ import annotations

from typing import override

from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPaintEvent, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mycad.core.drawing_text import TextStyle, TextStyleTable
from mycad.core.geometric_tolerance import (
    DatumIdentifier,
    DatumReference,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
from mycad.ui.font_manager import FontManager
from mycad.ui.geometric_tolerance_layout import layout_frame
from mycad.ui.geometric_tolerance_symbols import geometric_symbol
from mycad.ui.geometric_tolerance_templates import ToleranceTemplateStore
from mycad.ui.preserving_spinbox import PreservingDoubleSpinBox

_SYMBOLS = (
    ("直线度", "straightness"),
    ("平面度", "flatness"),
    ("圆度", "circularity"),
    ("圆柱度", "cylindricity"),
    ("线轮廓度", "line_profile"),
    ("面轮廓度", "surface_profile"),
    ("平行度", "parallelism"),
    ("垂直度", "perpendicularity"),
    ("倾斜度", "angularity"),
    ("位置度", "position"),
    ("同轴 / 同心度", "concentricity"),
    ("对称度", "symmetry"),
    ("圆跳动", "circular_runout"),
    ("全跳动", "total_runout"),
)


class FramePreview(QWidget):
    """Preview the same layout used for the drawing canvas."""

    def __init__(self, manager: FontManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.frame = FeatureControlFrame("0" * 32, (ToleranceRow("straightness", 0, 2),), (0, 0))
        self.text_style = TextStyle()
        self.error = ""
        self.setMinimumHeight(90)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(self.palette().text().color())
        if self.error:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.error)
            return
        layout = layout_frame(self.frame, self.manager, self.text_style)
        rotation = QTransform().rotate(-self.frame.rotation_deg)
        bounds = rotation.mapRect(layout.bounds)
        factor = min(
            max(self.width() - 20, 1) / max(bounds.width(), 1),
            max(self.height() - 20, 1) / max(bounds.height(), 1),
            5.0,
        )
        painter.translate(10 - bounds.left() * factor, 10 - bounds.top() * factor)
        painter.scale(factor, factor)
        painter.setTransform(rotation, True)
        layout.draw(painter)


def _modifier() -> QComboBox:
    combo = QComboBox()
    for label, value in (("无", ""), ("最大实体 M", "M"), ("最小实体 L", "L")):
        combo.addItem(label, value)
    return combo


class ToleranceRowEditor(QGroupBox):
    def __init__(
        self,
        row: ToleranceRow | None = None,
        parent: QWidget | None = None,
        *,
        available: tuple[DatumIdentifier, ...] = (),
    ) -> None:
        super().__init__("公差行", parent)
        self._available = available
        self._original_datums = () if row is None else row.datums
        self._explicit_datum_ids: dict[int, str] = {}
        root = QVBoxLayout(self)
        cells = QHBoxLayout()
        root.addLayout(cells)
        self.characteristic = QComboBox()
        self.characteristic.setIconSize(QSize(22, 22))
        for label, code in _SYMBOLS:
            image = QPixmap(24, 24)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(self.palette().text().color(), 1.5))
            painter.translate(4, 4)
            painter.scale(16, 16)
            pen = painter.pen()
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawPath(geometric_symbol(code))
            painter.end()
            self.characteristic.addItem(QIcon(image), label, code)
        self.value = PreservingDoubleSpinBox()
        self.value.setDecimals(8)
        self.value.setRange(0, 1e9)
        self.precision = QSpinBox()
        self.precision.setRange(0, 8)
        self.precision.setValue(2)
        self.diameter = QCheckBox("直径符号")
        self.modifier = _modifier()
        self.datums = tuple(QLineEdit() for _ in range(3))
        self.datum_modifiers = tuple(_modifier() for _ in range(3))
        self.datum_statuses = tuple(QLabel() for _ in range(3))
        self.datum_link_buttons = tuple(QPushButton("关联") for _ in range(3))
        self.exact_value_button = QPushButton("精确输入…")
        self.exact_value_button.clicked.connect(self._enter_exact_value)
        characteristic_cell = QVBoxLayout()
        characteristic_cell.addWidget(QLabel("特征"))
        characteristic_cell.addWidget(self.characteristic)
        self.symbol_palette_button = QPushButton("符号选择…")
        self.symbol_palette_button.clicked.connect(self._choose_symbol)
        characteristic_cell.addWidget(self.symbol_palette_button)
        characteristic_cell.addStretch()
        cells.addLayout(characteristic_cell)
        tolerance_cell = QVBoxLayout()
        tolerance_cell.addWidget(QLabel("公差值"))
        tolerance_cell.addWidget(self.value)
        tolerance_cell.addWidget(self.diameter)
        tolerance_cell.addWidget(self.modifier)
        precision_row = QHBoxLayout()
        precision_row.addWidget(QLabel("精度"))
        precision_row.addWidget(self.precision)
        precision_row.addWidget(self.exact_value_button)
        tolerance_cell.addLayout(precision_row)
        cells.addLayout(tolerance_cell)
        self.value_notice = QLabel()
        self.value_notice.setWordWrap(True)
        root.addWidget(self.value_notice)
        self.value.retained_changed.connect(self._update_value_notice)
        self.value.valueChanged.connect(self._update_value_notice)
        self.precision.valueChanged.connect(self._update_value_notice)
        for index, (datum, modifier, status, button) in enumerate(
            zip(
                self.datums,
                self.datum_modifiers,
                self.datum_statuses,
                self.datum_link_buttons,
                strict=True,
            )
        ):
            column = QVBoxLayout()
            column.addWidget(QLabel(f"基准 {index + 1}"))
            column.addWidget(datum)
            column.addWidget(modifier)
            column.addWidget(status)
            column.addWidget(button)
            column.addStretch()
            cells.addLayout(column)
        if row is not None:
            self.characteristic.setCurrentIndex(self.characteristic.findData(row.characteristic))
            self.value.set_preserved_value(row.value)
            self.precision.setValue(row.precision)
            self.diameter.setChecked(row.diameter)
            self.modifier.setCurrentIndex(self.modifier.findData(row.modifier))
            for index, datum in enumerate(row.datums):
                self.datums[index].setText(datum.label)
                self.datum_modifiers[index].setCurrentIndex(
                    self.datum_modifiers[index].findData(datum.modifier)
                )
        for index, (field, button) in enumerate(
            zip(self.datums, self.datum_link_buttons, strict=True)
        ):

            def update_status(_text: str, index: int = index) -> None:
                self._update_datum_status(index)

            field.textChanged.connect(update_status)
            button.clicked.connect(lambda _checked=False, index=index: self._link_datum(index))
            self._update_datum_status(index)

    def _choose_symbol(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("形位公差符号")
        grid = QGridLayout(dialog)
        for index, (label, code) in enumerate(_SYMBOLS):
            button = QToolButton(dialog)
            button.setObjectName(f"symbol_{code}")
            button.setText(label)
            button.setToolTip(label)
            button.setIcon(self.characteristic.itemIcon(index))
            button.setIconSize(QSize(24, 24))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)

            def select(_checked: bool = False, selected: int = index) -> None:
                self.characteristic.setCurrentIndex(selected)
                dialog.accept()

            button.clicked.connect(select)
            grid.addWidget(button, index // 4, index % 4)
        dialog.exec()

    def _update_value_notice(self) -> None:
        retained = self.value.retained_value
        notices = (
            []
            if retained is None
            else [f"原始值 {retained!r} 超出控件显示范围或精度；未修改时保留。"]
        )
        value = self.value.precise_value()
        if value != 0 and round(value, self.precision.value()) == 0:
            notices.append(
                "公差精度不足；请增加精度或检查数值，画布和 DXF 无法按当前精度正确显示。"
            )
        self.value_notice.setText(" ".join(notices))

    def _enter_exact_value(self) -> None:
        error = self.value.request_exact_value("公差值", minimum=0)
        if error is not None:
            self.value_notice.setText(error)

    def _datum_identity(
        self, index: int, label: str, available: tuple[DatumIdentifier, ...]
    ) -> str | None:
        matches = tuple(datum for datum in available if datum.label.casefold() == label.casefold())
        explicit = self._explicit_datum_ids.get(index)
        if explicit is not None:
            if len(matches) == 1 and matches[0].datum_id == explicit:
                return explicit
            self._explicit_datum_ids.pop(index, None)
        previous = self._original_datums[index] if index < len(self._original_datums) else None
        if previous is not None and previous.label.casefold() == label.casefold():
            if previous.datum_id is not None and any(
                datum.datum_id == previous.datum_id for datum in matches
            ):
                return previous.datum_id
            return None
        return matches[0].datum_id if len(matches) == 1 else None

    def _update_datum_status(self, index: int) -> None:
        label = self.datums[index].text().strip()
        matches = tuple(
            datum for datum in self._available if datum.label.casefold() == label.casefold()
        )
        identity = self._datum_identity(index, label, self._available) if label else None
        self.datum_statuses[index].setText("已关联" if identity else "未关联" if label else "")
        self.datum_link_buttons[index].setEnabled(
            bool(label) and len(matches) == 1 and identity is None
        )
        self.datum_link_buttons[index].setToolTip(
            "请先填写基准标签。"
            if not label
            else "请先创建同名基准标识。"
            if not matches
            else "同名基准不唯一，无法关联。"
            if len(matches) > 1
            else "已关联本图基准。"
            if identity
            else "关联本图中的同名基准标识。"
        )

    def _link_datum(self, index: int) -> None:
        label = self.datums[index].text().strip()
        matches = tuple(
            datum for datum in self._available if datum.label.casefold() == label.casefold()
        )
        if len(matches) == 1:
            self._explicit_datum_ids[index] = matches[0].datum_id
        self._update_datum_status(index)

    def value_row(self, available: tuple[DatumIdentifier, ...]) -> ToleranceRow:
        if self.value.input_error is not None:
            raise ValueError(self.value.input_error)
        refs: list[DatumReference] = []
        empty = False
        for index, (field, modifier) in enumerate(
            zip(self.datums, self.datum_modifiers, strict=True)
        ):
            label = field.text().strip()
            if not label:
                if modifier.currentData():
                    raise ValueError("空基准不能设置材料修饰符。")
                empty = True
                continue
            if empty:
                raise ValueError("基准必须按顺序填写，不能留空格。")
            identity = self._datum_identity(index, label, available)
            if identity is not None:
                label = next(
                    datum.label
                    for datum in available
                    if datum.datum_id == identity and datum.label.casefold() == label.casefold()
                )
            refs.append(DatumReference(label, identity, str(modifier.currentData())))
        return ToleranceRow(
            str(self.characteristic.currentData()),
            self.value.precise_value(),
            self.precision.value(),
            self.diameter.isChecked(),
            str(self.modifier.currentData()),
            tuple(refs),
        )


class SurfaceExtensionDialog(QDialog):
    """Edit the selected annotation's surface-extension distances."""

    def __init__(self, spec: SurfaceExtensionSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("表面延伸线")
        self.original = spec
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.offset = PreservingDoubleSpinBox()
        self.overshoot = PreservingDoubleSpinBox()
        for control, value in ((self.offset, spec.offset_mm), (self.overshoot, spec.overshoot_mm)):
            control.setRange(0, 1e9)
            control.setDecimals(8)
            control.setSuffix(" mm")
            control.set_preserved_value(value)
        for label, control in (("离开对象的间隙", self.offset), ("超出引线的长度", self.overshoot)):
            row = QHBoxLayout()
            row.addWidget(control)
            exact = QPushButton("精确输入…")
            exact.clicked.connect(
                lambda _checked=False, box=control, name=label: self._exact(box, name)
            )
            row.addWidget(exact)
            form.addRow(label, row)
        root.addLayout(form)
        self.message = QLabel("未编辑的高精度值会保留。")
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def value(self) -> SurfaceExtensionSpec:
        return SurfaceExtensionSpec(
            self.original.side,
            self.original.distance_mm,
            self.offset.precise_value(),
            self.overshoot.precise_value(),
        )

    def _exact(self, control: PreservingDoubleSpinBox, label: str) -> None:
        error = control.request_exact_value(label, minimum=0)
        if error is not None:
            self.message.setText(error)

    @override
    def accept(self) -> None:
        if self.offset.input_error is not None or self.overshoot.input_error is not None:
            self.message.setText("请修正精确输入的数值。")
            return
        try:
            self.value()
        except ValueError:
            self.message.setText("间隙必须小于目标距离与超出长度之和。")
            return
        super().accept()


class GeometricToleranceDialog(QDialog):
    def __init__(
        self,
        rows: tuple[ToleranceRow, ...] = (),
        available: tuple[DatumIdentifier, ...] = (),
        parent: QWidget | None = None,
        *,
        rotation_deg: float = 0.0,
        layer_names: tuple[str, ...] = ("0",),
        layer_name: str = "0",
        text_styles: TextStyleTable | None = None,
        text_style_id: str | None = None,
        font_manager: FontManager | None = None,
        template_store: ToleranceTemplateStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("形位公差")
        self.available = available
        self.text_styles = text_styles
        self.font_manager = font_manager or FontManager()
        self.template_store = template_store or ToleranceTemplateStore(QSettings("MyCAD", "MyCAD"))
        self.rows: list[ToleranceRowEditor] = []
        root = QVBoxLayout(self)
        explanation = QLabel("请按适用的 GB/ISO 标准核对符号与修饰符组合；本工具不判定工件合格。")
        explanation.setWordWrap(True)
        root.addWidget(explanation)
        properties = QFormLayout()
        self.rotation = PreservingDoubleSpinBox()
        self.rotation.setRange(-36000.0, 36000.0)
        self.rotation.setDecimals(3)
        self.rotation.setSuffix("°")
        self.rotation.set_preserved_value(rotation_deg)
        rotation_controls = QHBoxLayout()
        rotation_controls.addWidget(self.rotation)
        rotation_exact = QPushButton("精确输入…")
        rotation_exact.clicked.connect(self._enter_exact_rotation)
        rotation_controls.addWidget(rotation_exact)
        properties.addRow("旋转角度", rotation_controls)
        self.rotation_notice = QLabel()
        self.rotation_notice.setWordWrap(True)
        properties.addRow(self.rotation_notice)
        self.rotation.retained_changed.connect(self._update_rotation_notice)
        self._update_rotation_notice()
        self.layer = QComboBox()
        self.layer.addItems(layer_names)
        self.layer.setCurrentText(layer_name)
        properties.addRow("图层", self.layer)
        self.text_style = QComboBox()
        self.text_style.addItem("默认", None)
        if text_styles is not None:
            for style in text_styles.styles:
                self.text_style.addItem(style.name, style.style_id)
        selected_style = self.text_style.findData(text_style_id)
        if selected_style < 0:
            self.text_style.addItem(f"缺失样式：{text_style_id}", text_style_id)
            selected_style = self.text_style.count() - 1
        self.text_style.setCurrentIndex(selected_style)
        properties.addRow("文字样式", self.text_style)
        self.font_warning = QLabel()
        self.font_warning.setWordWrap(True)
        properties.addRow(self.font_warning)
        self.text_style.currentIndexChanged.connect(self._update_font_warning)
        self._update_font_warning()
        root.addLayout(properties)
        root.addWidget(QLabel("预览"))
        self.preview = FramePreview(self.font_manager)
        root.addWidget(self.preview)
        self.text_style.currentIndexChanged.connect(self._update_preview)
        self.rotation.valueChanged.connect(self._update_preview)
        self.rotation.retained_changed.connect(self._update_preview)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.rows_layout = QVBoxLayout(content)
        scroll.setWidget(content)
        root.addWidget(scroll)
        self.add_button = QPushButton("添加公差行")
        self.remove_button = QPushButton("删除最后一行")
        self.add_button.clicked.connect(self._add_clicked)
        self.remove_button.clicked.connect(self.remove_row)
        controls = QHBoxLayout()
        controls.addWidget(self.add_button)
        controls.addWidget(self.remove_button)
        root.addLayout(controls)
        self.message = QLabel()
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        templates = QHBoxLayout()
        templates.addWidget(QLabel("公差模板"))
        self.template_names = QComboBox()
        templates.addWidget(self.template_names, 1)
        self.save_template_button = QPushButton("保存当前行…")
        self.apply_template_button = QPushButton("应用…")
        self.delete_template_button = QPushButton("删除…")
        for button in (
            self.save_template_button,
            self.apply_template_button,
            self.delete_template_button,
        ):
            templates.addWidget(button)
        self.save_template_button.clicked.connect(self._save_template)
        self.apply_template_button.clicked.connect(self._apply_template)
        self.delete_template_button.clicked.connect(self._delete_template)
        root.addLayout(templates)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        for row in rows or (None,):
            self.add_row(row)
        self._refresh_templates()
        self.resize(1000, 620)

    def _refresh_templates(self, selected: str = "") -> None:
        try:
            names = self.template_store.names()
        except ValueError as exc:
            self.message.setText(str(exc))
            names = ()
        self.template_names.clear()
        self.template_names.addItems(names)
        if selected:
            self.template_names.setCurrentText(selected)
        self.apply_template_button.setEnabled(bool(names))
        self.delete_template_button.setEnabled(bool(names))

    def _save_template(self) -> None:
        try:
            rows = self.values()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        name, accepted = QInputDialog.getText(
            self, "保存公差模板", "模板名称（保存到本机，最多 80 字；名称不能重复）："
        )
        if not accepted:
            return
        try:
            self.template_store.save(name, rows)
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        self._refresh_templates(name)
        self.message.setText("模板已保存到本机；基准关联需在目标图纸重新确认。")

    def _apply_template(self) -> None:
        name = self.template_names.currentText()
        try:
            rows = self.template_store.get(name)
        except ValueError as exc:
            self.message.setText(str(exc))
            self._refresh_templates()
            return
        if (
            QMessageBox.question(
                self,
                "应用公差模板",
                "应用模板会替换当前公差行，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        while self.rows:
            row = self.rows.pop()
            self.rows_layout.removeWidget(row)
            row.deleteLater()
        for row in rows:
            self.add_row(row)
        self.message.setText("已应用模板；请检查数值并手动关联所需基准。")

    def _delete_template(self) -> None:
        name = self.template_names.currentText()
        if (
            QMessageBox.question(
                self,
                "删除公差模板",
                f"删除本机模板“{name}”？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.template_store.delete(name)
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        self._refresh_templates()
        self.message.setText("模板已删除。")

    def _update_rotation_notice(self) -> None:
        value = self.rotation.retained_value
        self.rotation_notice.setText(
            f"原始角度 {value!r} 超出控件显示范围或精度；未修改时保留。"
            if value is not None
            else ""
        )

    def _enter_exact_rotation(self) -> None:
        error = self.rotation.request_exact_value("旋转角度", minimum=-36000, maximum=36000)
        if error is not None:
            self.rotation_notice.setText(error)

    def _update_font_warning(self) -> None:
        identity = self.text_style.currentData()
        if identity is None:
            self.font_warning.clear()
            return
        if not isinstance(identity, str) or self.text_styles is None:
            self.font_warning.setText("文字样式不可用。")
            return
        try:
            style = self.text_styles.get(identity)
        except KeyError:
            self.font_warning.setText("文字样式不可用。")
            return
        replacement = self.font_manager.substitution(style)
        self.font_warning.setText(
            f"字体 {style.font_family or style.font_file} 不可用，使用 {replacement} 显示。"
            if replacement
            else ""
        )

    def add_row(self, row: ToleranceRow | None = None) -> None:
        if len(self.rows) >= 16:
            self.message.setText("最多支持 16 行。")
            return
        editor = ToleranceRowEditor(row, available=self.available)
        self.rows.append(editor)
        self.rows_layout.addWidget(editor)
        editor.characteristic.currentIndexChanged.connect(self._update_preview)
        editor.value.valueChanged.connect(self._update_preview)
        editor.value.retained_changed.connect(self._update_preview)
        editor.precision.valueChanged.connect(self._update_preview)
        editor.diameter.toggled.connect(self._update_preview)
        editor.modifier.currentIndexChanged.connect(self._update_preview)
        for field, modifier in zip(editor.datums, editor.datum_modifiers, strict=True):
            field.textChanged.connect(self._update_preview)
            modifier.currentIndexChanged.connect(self._update_preview)
        self._update_preview()

    def _update_preview(self) -> None:
        try:
            identity = self.text_style.currentData()
            self.preview.text_style = (
                self.text_styles.get(identity)
                if self.text_styles is not None and isinstance(identity, str)
                else TextStyle()
            )
            self.preview.frame = FeatureControlFrame(
                "0" * 32, self.values(), (0, 0), rotation_deg=self.rotation.precise_value()
            )
            self.preview.error = ""
        except (KeyError, ValueError) as exc:
            self.preview.error = str(exc)
        self.preview.update()

    def _add_clicked(self) -> None:
        self.add_row()

    def remove_row(self) -> None:
        if len(self.rows) > 1:
            self.rows.pop().deleteLater()
            self._update_preview()

    def values(self) -> tuple[ToleranceRow, ...]:
        return tuple(row.value_row(self.available) for row in self.rows)

    def accept(self) -> None:
        try:
            if self.rotation.input_error is not None:
                raise ValueError(self.rotation.input_error)
            self.values()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        super().accept()
