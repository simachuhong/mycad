# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""JSON-Schema-driven Qt editors using the command validator as authority."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mycad.commands.registry import CommandRegistry
from mycad.commands.spec import CommandSpec
from mycad.commands.validation import normalize_params, schema_matches, validate_params
from mycad.core.exceptions import ValidationError

_MISSING = object()
_OMIT = object()
_LENGTH_KEYS = frozenset(
    {
        "radius",
        "radius_mm",
        "diameter",
        "height",
        "width",
        "distance",
        "size_x",
        "size_y",
        "size_z",
    }
)
_FIELD_LABELS = {
    "size_x": "X 方向尺寸",
    "size_y": "Y 方向尺寸",
    "size_z": "Z 方向尺寸",
    "center": "中心点",
    "mode": "建模方式",
    "profile": "截面轮廓",
    "type": "截面类型",
    "radius": "半径",
    "width": "宽度",
    "height": "高度",
    "distance": "拉伸距离",
    "offset": "截面偏移",
    "target_face": "目标面条件",
    "surface": "面类型",
    "axis": "方向/轴线",
    "rank": "候选序号（从 0 开始）",
    "center_mm": "几何锚点",
    "radius_mm": "几何半径",
    "position": "孔位置",
    "diameter": "孔径",
    "depth": "孔深",
    "kind": "类型",
    "value": "数值",
    "edges": "目标边",
    "parent_faces": "相邻面条件",
    "curve": "边类型",
    "tool": "切除刀具",
    "count": "数量",
    "start_angle_deg": "起始角度",
    "angle_deg": "旋转角度",
}
_SCHEMA_BRANCH_LABELS = {
    "EdgeSelector": "几何条件",
    "FaceSelector": "几何条件",
    "Hole": "面孔",
    "InteractiveEdgeSelector": "视口锚定边",
    "InteractiveFaceSelector": "视口锚定面",
    "SketchHole": "草图孔",
    "SketchProfileReference": "引用草图",
}
_SCHEMA_CONST_LABELS = {
    "arc": "圆弧",
    "blind": "盲孔",
    "center": "面心",
    "circle": "圆",
    "face": "选定面",
    "line": "直线",
    "point": "指定点",
    "polyline": "多段线",
    "rectangle": "矩形",
    "sketch": "草图",
    "through_all": "贯穿",
}


def _schema_object(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def _resolve_schema(schema: Mapping[str, object], defs: Mapping[str, object]) -> dict[str, object]:
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        name = ref.removeprefix("#/$defs/")
        target = defs.get(name)
        if isinstance(target, dict):
            return _resolve_schema(cast("Mapping[str, object]", target), defs)
    return dict(schema)


def _unit_for_path(path: str, schema: Mapping[str, object]) -> str | None:
    key = path.rsplit(".", 1)[-1].split("[", 1)[0]
    if key.endswith("_deg"):
        return "deg"
    if key in _LENGTH_KEYS or key in {"center", "center_mm", "origin", "position"}:
        return "mm"
    if schema.get("type") == "array" and path.rsplit(".", 1)[-1] in {"center", "center_mm"}:
        return "mm"
    return None


def _branch_label(schema: object, fallback: int, defs: Mapping[str, object]) -> str:
    source = _schema_object(schema)
    ref = source.get("$ref")
    if isinstance(ref, str):
        label = _SCHEMA_BRANCH_LABELS.get(ref.removeprefix("#/$defs/"))
        if label is not None:
            return label
    record = _resolve_schema(source, defs)
    properties = _schema_object(record.get("properties"))
    for _key, value in properties.items():
        const = _schema_object(value).get("const")
        if isinstance(const, str):
            return _SCHEMA_CONST_LABELS.get(const, const)
    return f"选项 {fallback + 1}"


def _branch_for_value(
    branches: list[object], value: object, defs: Mapping[str, object]
) -> int | None:
    matching_branches = [
        index
        for index, branch in enumerate(branches)
        if schema_matches(_schema_object(branch), value, defs)
    ]
    if len(matching_branches) == 1:
        return matching_branches[0]
    # Incomplete values can still identify a branch by its discriminator,
    # allowing the user to finish its required fields in the form.
    if not isinstance(value, Mapping):
        return None
    values = cast("Mapping[str, object]", value)
    for index, branch in enumerate(branches):
        properties = _schema_object(_resolve_schema(_schema_object(branch), defs).get("properties"))
        has_discriminator = False
        matches = True
        for key, schema in properties.items():
            constant = _schema_object(schema).get("const")
            if constant is None:
                continue
            has_discriminator = True
            if values.get(key) != constant:
                matches = False
                break
        if has_discriminator and matches:
            return index
    if values:
        compatible = [
            index
            for index, branch in enumerate(branches)
            if set(values).issubset(
                _schema_object(_resolve_schema(_schema_object(branch), defs).get("properties"))
            )
        ]
        if len(compatible) == 1:
            return compatible[0]
    return None


class _NumberField(QDoubleSpinBox):
    """Keep supplied geometry precision until the displayed number is edited."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._exact_value = 0.0
        self.valueChanged.connect(self._remember_edit)

    def _remember_edit(self, value: float) -> None:
        self._exact_value = value

    def setValue(self, value: float) -> None:  # noqa: N802 (Qt override)
        super().setValue(value)
        self._exact_value = max(self.minimum(), min(value, self.maximum()))

    def value(self) -> float:
        return self._exact_value


class VectorField(QWidget):
    """Fixed-size numeric vector with one spin box per component."""

    def __init__(
        self,
        size: int,
        values: object,
        unit: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        entries: Sequence[object] = (
            cast("Sequence[object]", values) if isinstance(values, list | tuple) else ()
        )
        self._components: list[QDoubleSpinBox] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for index in range(size):
            component = _NumberField(self)
            component.setDecimals(6)
            component.setRange(-1_000_000_000.0, 1_000_000_000.0)
            entry = entries[index] if index < len(entries) else 0.0
            component.setValue(float(entry) if isinstance(entry, int | float) else 0.0)
            if unit:
                component.setSuffix(f" {unit}")
            component.setAccessibleName(f"分量 {index + 1}")
            layout.addWidget(component)
            self._components.append(component)

    def value(self) -> list[float]:
        """Return component values in schema order."""

        return [component.value() for component in self._components]

    def set_value(self, value: object) -> None:
        """Fill all components from a sequence of numbers."""

        if not isinstance(value, list | tuple):
            raise ValueError("vector value has the wrong number of components")
        entries = cast("Sequence[object]", value)
        if len(entries) != len(self._components):
            raise ValueError("vector value has the wrong number of components")
        for component, entry in zip(self._components, entries, strict=True):
            if isinstance(entry, bool) or not isinstance(entry, int | float):
                raise ValueError("vector components must be numeric")
            component.setValue(float(entry))


class _SchemaEditor:
    """Build one editor tree from the project's fixed JSON-Schema subset."""

    def __init__(
        self,
        schema: Mapping[str, object],
        value: object,
        defs: Mapping[str, object],
        path: str,
        editors: dict[str, _SchemaEditor],
        parent: QWidget | None = None,
        *,
        register: bool = True,
    ) -> None:
        self._schema = _resolve_schema(schema, defs)
        if value is _MISSING and "default" in self._schema:
            value = self._schema["default"]
        self._defs = defs
        self.path = path
        self._editors = editors
        self.widget = QWidget(parent)
        self.control: object
        self.unit = _unit_for_path(path, self._schema)
        self._build(value)
        if path and register:
            editors[path] = self

    def _build(self, value: object) -> None:
        layout = QHBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        branches_raw = self._schema.get("oneOf")
        if isinstance(branches_raw, list):
            editor = _OneOfEditor(
                cast("list[object]", branches_raw),
                value,
                self._defs,
                self.path,
                self._editors,
                self.widget,
            )
            layout.addWidget(editor)
            self.control = editor
            return

        declared = self._schema.get("type")
        if declared == "object":
            editor = _ObjectEditor(
                self._schema,
                value,
                self._defs,
                self.path,
                self._editors,
                self.widget,
            )
            layout.addWidget(editor)
            self.control = editor
            return

        if declared == "array":
            item_schema = _resolve_schema(_schema_object(self._schema.get("items")), self._defs)
            minimum = self._schema.get("minItems")
            maximum = self._schema.get("maxItems")
            if (
                item_schema.get("type") == "number"
                and isinstance(minimum, int)
                and minimum == maximum
            ):
                default = self._schema.get("default", _MISSING) if value is _MISSING else value
                if default is _MISSING:
                    default = cast("object", list[object]())
                editor = VectorField(minimum, default, self.unit, self.widget)
                self.control = editor
            elif item_schema.get("type") == "object" or "oneOf" in item_schema:
                editor = _ObjectArrayEditor(
                    _schema_object(self._schema.get("items")),
                    value,
                    self._defs,
                    self.path,
                    self._editors,
                    self.widget,
                )
                self.control = editor
            else:
                text = QPlainTextEdit(self.widget)
                text.setMaximumHeight(90)
                text.setPlainText(
                    json.dumps(value if isinstance(value, list) else [], ensure_ascii=False)
                )
                self.control = text
                editor = text
            layout.addWidget(editor)
            return

        if "const" in self._schema:
            constant = self._schema["const"]
            label = QLabel(str(constant), self.widget)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.control = constant
            layout.addWidget(label)
            return

        if declared == "number":
            spin = _NumberField(self.widget)
            spin.setDecimals(6)
            spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
            if self.unit:
                spin.setSuffix(f" {self.unit}")
            current = (
                value if isinstance(value, int | float) and not isinstance(value, bool) else 0.0
            )
            spin.setValue(float(current))
            self.control = spin
            layout.addWidget(spin)
            return

        if declared == "integer":
            spin_int = QSpinBox(self.widget)
            spin_int.setRange(-2_147_483_648, 2_147_483_647)
            current = value if isinstance(value, int) and not isinstance(value, bool) else 0
            spin_int.setValue(current)
            self.control = spin_int
            layout.addWidget(spin_int)
            return

        if declared == "boolean":
            checkbox = QCheckBox(self.widget)
            checkbox.setChecked(value if isinstance(value, bool) else False)
            self.control = checkbox
            layout.addWidget(checkbox)
            return

        if declared == "string" and isinstance(self._schema.get("enum"), list):
            combo = QComboBox(self.widget)
            options = cast("list[object]", self._schema["enum"])
            has_value = value in options
            if not has_value and "default" not in self._schema:
                combo.addItem("请选择…", _OMIT)
            for option in options:
                combo.addItem(str(option), option)
            default = self._schema.get("default", value)
            index = combo.findData(default)
            combo.setCurrentIndex(index if index >= 0 else 0)
            self.control = combo
            layout.addWidget(combo)
            return

        if declared == "string":
            line = QLineEdit(self.widget)
            line.setText(value if isinstance(value, str) else "")
            self.control = line
            layout.addWidget(line)
            return

        text = QPlainTextEdit(self.widget)
        text.setMaximumHeight(90)
        text.setPlainText(json.dumps(value, ensure_ascii=False) if value is not _MISSING else "")
        self.control = text
        layout.addWidget(text)

    def value(self) -> object:
        control = self.control
        if isinstance(control, QDoubleSpinBox):
            return control.value()
        if isinstance(control, QSpinBox):
            return control.value()
        if isinstance(control, QCheckBox):
            return control.isChecked()
        if isinstance(control, QComboBox):
            return control.currentData()
        if isinstance(control, QLineEdit):
            return control.text()
        if isinstance(control, QPlainTextEdit):
            raw = control.toPlainText()
            if not raw.strip():
                return cast("list[object]", []) if self._schema.get("type") == "array" else _OMIT
            try:
                parsed: object = cast("object", json.loads(raw))
            except json.JSONDecodeError as exc:
                raise ValidationError(f"{self.path}: invalid JSON: {exc.msg}") from exc
            if self._schema.get("type") == "array" and not isinstance(parsed, list):
                raise ValidationError(f"{self.path}: expected a JSON array")
            return cast("list[object]", parsed) if isinstance(parsed, list) else parsed
        if isinstance(control, VectorField):
            return control.value()
        if isinstance(control, (_ObjectEditor, _ObjectArrayEditor, _OneOfEditor)):
            return control.value()
        return control

    def set_value(self, value: object) -> None:
        control = self.control
        if isinstance(control, QDoubleSpinBox):
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{self.path} expects a number")
            control.setValue(float(value))
        elif isinstance(control, QSpinBox):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{self.path} expects an integer")
            control.setValue(value)
        elif isinstance(control, QCheckBox):
            control.setChecked(value if isinstance(value, bool) else False)
        elif isinstance(control, QComboBox):
            index = control.findData(value)
            if index < 0:
                raise ValueError(f"{self.path} value {value!r} is not an option")
            control.setCurrentIndex(index)
        elif isinstance(control, QLineEdit):
            control.setText(str(value))
        elif isinstance(control, QPlainTextEdit):
            control.setPlainText(json.dumps(value, ensure_ascii=False))
        elif isinstance(control, VectorField | _ObjectEditor | _ObjectArrayEditor | _OneOfEditor):
            control.set_value(value)
        elif value == control:
            return
        else:
            raise ValueError(f"{self.path} is not editable")


class _FieldSlot(QWidget):
    def __init__(
        self,
        editor: _SchemaEditor,
        enabled: bool,
        optional: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.editor = editor
        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #b42318")
        self.error_label.setVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self._toggle: QCheckBox | None = None
        if optional:
            toggle = QCheckBox("启用", self)
            toggle.setChecked(enabled)
            toggle.toggled.connect(editor.widget.setEnabled)
            self._toggle = toggle
            row.addWidget(toggle)
        editor.widget.setEnabled(enabled)
        row.addWidget(editor.widget, 1)
        layout.addLayout(row)
        layout.addWidget(self.error_label)

    def value(self) -> object:
        if self._toggle is not None and not self._toggle.isChecked():
            return _OMIT
        return self.editor.value()

    @property
    def path(self) -> str:
        """Schema path rendered by this row."""

        return self.editor.path

    def set_value(self, value: object) -> None:
        if self._toggle is not None:
            self._toggle.setChecked(True)
        self.editor.set_value(value)


class _ObjectEditor(QWidget):
    def __init__(
        self,
        schema: Mapping[str, object],
        value: object,
        defs: Mapping[str, object],
        path: str,
        editors: dict[str, _SchemaEditor],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        record: Mapping[str, object] = (
            cast("Mapping[str, object]", value) if isinstance(value, Mapping) else {}
        )
        properties = _schema_object(schema.get("properties"))
        self._extras: dict[str, object] = {
            key: item for key, item in record.items() if key not in properties
        }
        required_raw = schema.get("required", [])
        required_items = (
            cast("list[object]", required_raw) if isinstance(required_raw, list) else []
        )
        required = {item for item in required_items if isinstance(item, str)}
        self.slots: dict[str, _FieldSlot] = {}
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for key, property_value in properties.items():
            prop_schema = _schema_object(property_value)
            resolved = _resolve_schema(prop_schema, defs)
            current: object = record.get(key, _MISSING)
            if current is _MISSING:
                current = resolved.get("default", resolved.get("const", _MISSING))
            has_default = "default" in resolved or "const" in resolved
            is_required = key in required
            enabled = is_required or has_default or key in record
            field_path = f"{path}.{key}" if path else key
            editor = _SchemaEditor(
                prop_schema,
                current,
                defs,
                field_path,
                editors,
                self,
            )
            slot = _FieldSlot(editor, enabled, not enabled, self)
            self.slots[key] = slot
            layout.addRow(_FIELD_LABELS.get(key, key), slot)

    def value(self) -> dict[str, object]:
        result = dict(self._extras)
        for key, slot in self.slots.items():
            value = slot.value()
            if value is not _OMIT:
                result[key] = value
        return result

    def set_value(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise ValueError("object field expects a mapping")
        values = cast("Mapping[str, object]", value)
        for key, entry in values.items():
            slot = self.slots.get(key)
            if slot is not None:
                slot.set_value(entry)
            else:
                self._extras[key] = entry


class _OneOfEditor(QWidget):
    def __init__(
        self,
        branches: list[object],
        value: object,
        defs: Mapping[str, object],
        path: str,
        editors: dict[str, _SchemaEditor],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._branches = branches
        self._defs = defs
        self._path = path
        self._editors = editors
        self._value = value
        self.branch: _SchemaEditor | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.selector = QComboBox(self)
        self.selector.addItem("请选择…", _OMIT)
        for index, branch in enumerate(branches):
            self.selector.addItem(_branch_label(branch, index, defs), index)
        layout.addWidget(self.selector)
        self._branch_container = QWidget(self)
        self._branch_layout = QVBoxLayout(self._branch_container)
        self._branch_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._branch_container)
        selected = _branch_for_value(branches, value, defs)
        self.selector.setCurrentIndex(selected + 1 if selected is not None else 0)
        self.selector.currentIndexChanged.connect(self._select_branch)
        if selected is not None:
            self._select_branch(self.selector.currentIndex())

    def _select_branch(self, combo_index: int) -> None:
        previous_value = self.value()
        if previous_value is _OMIT:
            previous_value = self._value
        self._replace_branch(combo_index, previous_value)

    def _replace_branch(self, combo_index: int, value: object) -> None:
        while self._branch_layout.count():
            child = self._branch_layout.takeAt(0)
            if child is None:
                continue
            widget = child.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.branch = None
        for path in tuple(self._editors):
            if path.startswith(f"{self._path}.") or path.startswith(f"{self._path}["):
                del self._editors[path]
        branch_index = self.selector.itemData(combo_index)
        if not isinstance(branch_index, int) or not 0 <= branch_index < len(self._branches):
            return
        branch_schema = _schema_object(self._branches[branch_index])
        resolved = _resolve_schema(branch_schema, self._defs)
        branch_properties = _schema_object(resolved.get("properties"))
        branch_value: object = value
        if resolved.get("type") == "object" and isinstance(value, Mapping):
            values = cast("Mapping[str, object]", value)
            branch_value = {key: entry for key, entry in values.items() if key in branch_properties}
        self.branch = _SchemaEditor(
            branch_schema,
            branch_value,
            self._defs,
            self._path,
            self._editors,
            self._branch_container,
            register=False,
        )
        self._branch_layout.addWidget(self.branch.widget)

    def value(self) -> object:
        return _OMIT if self.branch is None else self.branch.value()

    def set_value(self, value: object) -> None:
        index = _branch_for_value(self._branches, value, self._defs)
        if index is None:
            raise ValueError(f"{self._path} value does not match a oneOf branch")
        self._value = value
        combo_index = index + 1
        self.selector.blockSignals(True)
        self.selector.setCurrentIndex(combo_index)
        self.selector.blockSignals(False)
        self._replace_branch(combo_index, value)


class _ObjectArrayEditor(QWidget):
    def __init__(
        self,
        item_schema: Mapping[str, object],
        value: object,
        defs: Mapping[str, object],
        path: str,
        editors: dict[str, _SchemaEditor],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._item_schema = item_schema
        self._defs = defs
        self._path = path
        self._editors = editors
        self.rows: list[tuple[_SchemaEditor, QWidget]] = []
        self._items_layout = QVBoxLayout(self)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._add_button = QPushButton("添加", self)
        self._add_button.clicked.connect(lambda: self._append(_MISSING))
        values = cast("list[object]", value) if isinstance(value, list) else []
        for entry in values:
            self._append(entry)
        self._items_layout.addWidget(self._add_button)

    def _append(self, value: object) -> None:
        index = len(self.rows)
        row = QWidget(self)
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        editor = _SchemaEditor(
            self._item_schema,
            value,
            self._defs,
            f"{self._path}[{index}]",
            self._editors,
            row,
        )
        remove = QPushButton("移除", row)
        remove.clicked.connect(lambda: self._remove(row))
        row_layout.addWidget(editor.widget)
        row_layout.addWidget(remove, alignment=Qt.AlignmentFlag.AlignRight)
        self._items_layout.insertWidget(len(self.rows), row)
        self.rows.append((editor, row))

    def _remove(self, row: QWidget) -> None:
        for index, (_editor, candidate) in enumerate(self.rows):
            if candidate is row:
                self.rows.pop(index)
                candidate.deleteLater()
                return

    def value(self) -> list[object]:
        return [editor.value() for editor, _row in self.rows]

    def set_value(self, value: object) -> None:
        if not isinstance(value, list):
            raise ValueError(f"{self._path} expects an array")
        entries = cast("list[object]", value)
        for _editor, row in self.rows:
            row.hide()
            row.deleteLater()
        for path in tuple(self._editors):
            if path.startswith(f"{self._path}["):
                del self._editors[path]
        self.rows.clear()
        while self._items_layout.count() > 1:
            self._items_layout.takeAt(0)
        for entry in entries:
            self._append(entry)


class ParameterForm(QWidget):
    """Render a command's schema and validate through the shared registry rules."""

    values_changed = Signal()

    def __init__(
        self,
        spec: CommandSpec,
        values: Mapping[str, object],
        registry: CommandRegistry,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._spec = spec
        self._registry = registry
        self._editors: dict[str, _SchemaEditor] = {}
        self._error_slots: dict[str, _FieldSlot] = {}
        self.errors: dict[str, str] = {}
        schema = _resolve_schema(spec.params_schema, registry.schema_defs)
        self._root = _SchemaEditor(schema, values, registry.schema_defs, "", self._editors, self)
        layout = QVBoxLayout(self)
        layout.addWidget(self._root.widget)
        self._index_error_slots()
        for control in self.findChildren(QDoubleSpinBox):
            control.valueChanged.connect(self._notify_values_changed)
        for control in self.findChildren(QSpinBox):
            control.valueChanged.connect(self._notify_values_changed)
        for control in self.findChildren(QAbstractButton):
            control.clicked.connect(self._notify_values_changed)
            control.toggled.connect(self._notify_values_changed)
        for control in self.findChildren(QComboBox):
            control.currentIndexChanged.connect(self._notify_values_changed)
        for control in self.findChildren(QLineEdit):
            control.textEdited.connect(self._notify_values_changed)
        for control in self.findChildren(QPlainTextEdit):
            control.textChanged.connect(self._notify_values_changed)

    def _notify_values_changed(self, *_args: object) -> None:
        self.values_changed.emit()

    def _index_error_slots(self) -> None:
        self._error_slots.clear()

        def walk(editor: _SchemaEditor) -> None:
            control = editor.control
            if isinstance(control, _ObjectEditor):
                for child in control.slots.values():
                    self._error_slots[_normalize_path(child.path)] = child
                    walk(child.editor)
            elif isinstance(control, _ObjectArrayEditor):
                for child, _row in control.rows:
                    walk(child)
            elif isinstance(control, _OneOfEditor) and control.branch is not None:
                walk(control.branch)

        walk(self._root)

    def field_widget(self, path: str) -> QWidget | None:
        """Return the editable widget for one dotted schema path."""

        self._index_error_slots()
        editor = self._editors.get(path)
        if editor is None:
            return None
        control = editor.control
        return control if isinstance(control, QWidget) else None

    def unit_for(self, path: str) -> str | None:
        """Return the displayed unit for a field, when its schema is dimensional."""

        self._index_error_slots()
        editor = self._editors.get(path)
        return None if editor is None else editor.unit

    def set_value(self, path: str, value: object) -> None:
        """Set a field programmatically, including values supplied by selectors."""

        self._index_error_slots()
        editor = self._editors.get(path)
        if editor is None:
            raise KeyError(path)
        slot = self._error_slots.get(_normalize_path(path))
        if slot is not None:
            slot.set_value(value)
        else:
            editor.set_value(value)

    def set_selector(self, path: str, value: object) -> None:
        """Selector-fill seam for face/edge pickers and coordinate capture."""

        self.set_value(path, value)

    def set_path_visible(self, path: str, visible: bool) -> None:
        """Show or hide a composite schema row while retaining its stored value."""

        self._index_error_slots()
        slot = self._error_slots.get(_normalize_path(path))
        if slot is None:
            raise KeyError(path)
        parent = slot.parentWidget()
        layout = parent.layout() if parent is not None else None
        if isinstance(layout, QFormLayout):
            layout.setRowVisible(slot, visible)
        else:
            slot.setVisible(visible)

    def normalized_params(self) -> dict[str, object]:
        """Collect widget values and pass them through the command validator."""

        self._index_error_slots()
        self.errors.clear()
        for slot in self._error_slots.values():
            slot.error_label.clear()
            slot.error_label.setVisible(False)
        try:
            value = self._root.value()
            if not isinstance(value, Mapping):
                raise ValidationError("parameters: choose a schema option before validating")
            raw = cast("Mapping[str, object]", value)
            validated = validate_params(self._spec, raw, self._registry.schema_defs)
            return normalize_params(validated)
        except ValidationError as exc:
            error_path = str(exc).split(":", 1)[0]
            normalized_path = _normalize_path(error_path)
            self.errors[normalized_path] = str(exc)
            slot = self._error_slots.get(normalized_path)
            if slot is None:
                slot = self._error_slots.get(normalized_path.split(".", 1)[0])
            if slot is not None:
                slot.error_label.setText(str(exc))
                slot.error_label.setVisible(True)
            raise


def _normalize_path(path: str) -> str:
    return re.sub(r"\[(\d+)\]", r".\1", path)


__all__ = ["ParameterForm", "VectorField"]
