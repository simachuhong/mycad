# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Reusable editor for a single dimension tolerance configuration."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mycad.core.dimension_tolerance import DimensionTolerance, tolerance_values_hidden_by_precision
from mycad.ui.preserving_spinbox import PreservingDoubleSpinBox


class DimensionToleranceEditor(QWidget):
    """Edit signed deviations and layout without touching document state."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        self.mode = QComboBox()
        for title, mode in (
            ("无", "none"),
            ("对称", "symmetric"),
            ("上下偏差", "deviation"),
            ("极限尺寸", "limits"),
        ):
            self.mode.addItem(title, mode)
        self.upper_spin = PreservingDoubleSpinBox()
        self.lower_spin = PreservingDoubleSpinBox()
        for spin in (self.upper_spin, self.lower_spin):
            spin.setDecimals(8)
            spin.setRange(-1e9, 1e9)
        self.precision = QSpinBox()
        self.precision.setRange(0, 8)
        self.factor = PreservingDoubleSpinBox()
        self.factor.setDecimals(3)
        self.factor.setRange(0.001, 100)
        self.alignment = QComboBox()
        for label, value in (("上对齐", "top"), ("居中", "middle"), ("下对齐", "bottom")):
            self.alignment.addItem(label, value)
        self.exact_upper_button = QPushButton("精确输入…")
        self.exact_lower_button = QPushButton("精确输入…")
        self.exact_factor_button = QPushButton("精确输入…")
        self.exact_upper_button.clicked.connect(
            lambda: self._enter_exact_value(self.upper_spin, "上偏差")
        )
        self.exact_lower_button.clicked.connect(
            lambda: self._enter_exact_value(self.lower_spin, "下偏差")
        )
        self.exact_factor_button.clicked.connect(
            lambda: self._enter_exact_value(self.factor, "字高比例", positive=True, maximum=100)
        )
        self._previous_mode: str | None = None
        self._nominal: float | None = None

        def field(spin: PreservingDoubleSpinBox, button: QPushButton) -> QWidget:
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(spin)
            layout.addWidget(button)
            return widget

        for label, widget in (
            ("方式", self.mode),
            ("上偏差 / 对称值", field(self.upper_spin, self.exact_upper_button)),
            ("下偏差", field(self.lower_spin, self.exact_lower_button)),
            ("公差精度", self.precision),
            ("字高比例", field(self.factor, self.exact_factor_button)),
            ("垂直对齐", self.alignment),
        ):
            form.addRow(label, widget)
        self.value_notice = QLabel()
        self.value_notice.setWordWrap(True)
        form.addRow(self.value_notice)
        for spin in (self.upper_spin, self.lower_spin, self.factor):
            spin.retained_changed.connect(self._update_value_notice)
            spin.valueChanged.connect(self._update_value_notice)
        self.precision.valueChanged.connect(self._update_value_notice)
        self.mode.currentIndexChanged.connect(self._sync_enabled)
        self.set_value(DimensionTolerance())

    def _sync_enabled(self) -> None:
        mode = str(self.mode.currentData())
        if self._previous_mode == "symmetric" and mode != "symmetric":
            upper = self.upper_spin.precise_value()
            if self.upper_spin.input_error is None and upper >= 0:
                self.lower_spin.set_preserved_value(-upper)
        self._previous_mode = mode
        self.lower_spin.setEnabled(mode in ("deviation", "limits"))
        self.upper_spin.setEnabled(mode != "none")
        self.exact_lower_button.setEnabled(mode in ("deviation", "limits"))
        self.exact_upper_button.setEnabled(mode != "none")
        self._update_value_notice()

    def _enter_exact_value(
        self,
        spin: PreservingDoubleSpinBox,
        label: str,
        *,
        positive: bool = False,
        maximum: float | None = None,
    ) -> None:
        error = spin.request_exact_value(label, positive=positive, maximum=maximum)
        if error is not None:
            self.value_notice.setText(error)

    def _update_value_notice(self) -> None:
        values = tuple(
            f"{name} {spin.retained_value!r}"
            for name, spin in (
                ("上偏差", self.upper_spin),
                ("下偏差", self.lower_spin),
                ("字高比例", self.factor),
            )
            if spin.retained_value is not None
        )
        notices = (
            ["原始值 " + "、".join(values) + " 超出控件显示范围或精度；未修改时保留。"]
            if values
            else []
        )
        try:
            value = self.value()
            if (
                value.mode != "limits" or self._nominal is not None
            ) and tolerance_values_hidden_by_precision(self._nominal or 0.0, value):
                notices.append(
                    "公差精度不足；请增加精度或检查偏差，画布和 DXF 无法按当前精度正确显示。"
                )
        except ValueError:
            pass
        self.value_notice.setText(" ".join(notices))

    def set_nominal(self, nominal: float | None) -> None:
        """Supply the actual measurement for limit-display validation."""
        self._nominal = nominal
        self._update_value_notice()

    def set_value(self, value: DimensionTolerance) -> None:
        self._previous_mode = None
        self.mode.setCurrentIndex(self.mode.findData(value.mode))
        self.upper_spin.set_preserved_value(value.upper_deviation)
        self.lower_spin.set_preserved_value(value.lower_deviation)
        self.precision.setValue(value.precision)
        self.factor.set_preserved_value(value.text_factor)
        self.alignment.setCurrentIndex(self.alignment.findData(value.alignment))
        self._sync_enabled()

    def value(self) -> DimensionTolerance:
        mode = str(self.mode.currentData())
        for spin in (
            self.factor,
            *((self.upper_spin,) if mode != "none" else ()),
            *((self.lower_spin,) if mode in ("deviation", "limits") else ()),
        ):
            if spin.input_error is not None:
                raise ValueError(spin.input_error)
        upper = self.upper_spin.precise_value()
        lower = -upper if mode == "symmetric" else self.lower_spin.precise_value()
        if mode == "none" and upper < lower:
            # Disabling must remain possible even if the staged pair is invalid.
            upper = lower = 0.0
        return DimensionTolerance(
            mode,
            upper,
            lower,
            self.precision.value(),
            self.factor.precise_value(),
            str(self.alignment.currentData()),
        )


class DimensionToleranceDialog(QDialog):
    """Stage a single dimension's override or inheritance choice."""

    def __init__(
        self,
        value: DimensionTolerance | None,
        default: DimensionTolerance,
        parent: QWidget | None = None,
        *,
        nominal: float | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("尺寸公差")
        layout = QVBoxLayout(self)
        self.inherit = QCheckBox("继承标注样式")
        self.inherit.setChecked(value is None)
        layout.addWidget(self.inherit)
        self.editor = DimensionToleranceEditor()
        self.editor.set_nominal(nominal)
        self.editor.set_value(default if value is None else value)
        self.editor.setEnabled(value is not None)
        self.inherit.toggled.connect(self._inherit_changed)
        layout.addWidget(self.editor)
        self.message = QLabel()
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_value(self) -> DimensionTolerance | None:
        return None if self.inherit.isChecked() else self.editor.value()

    def _inherit_changed(self, checked: bool) -> None:
        self.editor.setEnabled(not checked)

    def accept(self) -> None:
        try:
            self.selected_value()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        super().accept()
