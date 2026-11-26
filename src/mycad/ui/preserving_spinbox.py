# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Preserve existing values that a numeric editor cannot display exactly."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QInputDialog, QWidget


class PreservingDoubleSpinBox(QDoubleSpinBox):
    """Keep an undisplayable loaded value until this field is actually edited."""

    retained_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._retained: float | None = None
        self._input_error: str | None = None
        self.valueChanged.connect(self._clear_retained)
        self.lineEdit().textEdited.connect(self._clear_retained)

    def set_preserved_value(self, value: float) -> None:
        with QSignalBlocker(self):
            self.setValue(value)
        self._retained = value if self.value() != value else None
        self._input_error = None
        self.retained_changed.emit()

    @property
    def retained_value(self) -> float | None:
        return self._retained

    @property
    def input_error(self) -> str | None:
        return self._input_error

    def precise_value(self) -> float:
        return self.value() if self._retained is None else self._retained

    def request_exact_value(
        self,
        label: str,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
        positive: bool = False,
    ) -> str | None:
        text, accepted = QInputDialog.getText(
            self, "精确输入", f"{label}（支持科学计数法）：", text=repr(self.precise_value())
        )
        if not accepted:
            if self._input_error is not None:
                self._input_error = None
                self.retained_changed.emit()
            return None
        try:
            decimal_value = Decimal(text.strip())
            value = float(decimal_value)
        except (InvalidOperation, ValueError, OverflowError):
            self._input_error = "请输入有限数值。"
            return self._input_error
        if not decimal_value.is_finite() or not math.isfinite(value):
            self._input_error = "请输入有限数值。"
            return self._input_error
        if value == 0 and decimal_value != 0:
            self._input_error = "数值超出可表示范围。"
            return self._input_error
        if (
            (minimum is not None and value < minimum)
            or (maximum is not None and value > maximum)
            or (positive and value <= 0)
        ):
            self._input_error = "数值超出允许范围。"
            return self._input_error
        self.set_preserved_value(value)
        return None

    def _clear_retained(self, *_args: object) -> None:
        if self._retained is not None or self._input_error is not None:
            self._retained = None
            self._input_error = None
            self.retained_changed.emit()
