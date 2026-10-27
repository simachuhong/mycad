# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Strict JSON command boundary for engineering drawing objects."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, cast
from uuid import UUID

from mycad.core.drawing import (
    AnnotationKind,
    DrawingAnnotation,
    DrawingOperation,
    DrawingSheet,
    DrawingState,
    DrawingView,
    ProjectionAngle,
    SourceBinding,
    apply_drawing_operation,
)
from mycad.core.drawing_projection import Point2, Point3, ViewBasis, ViewDirection, finite
from mycad.core.drawing_references import DrawingGeometryReference


def _record(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("drawing object must be a mapping")
    result = cast("Mapping[object, object]", value)
    if any(not isinstance(key, str) for key in result):
        raise ValueError("drawing object keys must be strings")
    return dict(cast("Mapping[str, object]", result))


def _items(value: object) -> Sequence[object]:
    if not isinstance(value, list | tuple):
        raise ValueError("expected drawing array")
    return cast("Sequence[object]", value)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expected drawing text")
    return value


def _uuid(value: object) -> UUID:
    raw = _text(value)
    parsed = UUID(raw)
    if raw not in (str(parsed), parsed.hex):
        raise ValueError("expected canonical drawing UUID")
    return parsed


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("expected drawing number")
    finite((value,), "drawing number")
    return float(value)


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("expected drawing boolean")
    return value


def _point(value: object, count: int) -> tuple[float, ...]:
    items = _items(value)
    if len(items) != count:
        raise ValueError(f"expected {count} coordinates")
    return tuple(_number(item) for item in items)


def _reference(value: object) -> DrawingGeometryReference:
    obj = _record(value)
    if set(obj) - {"kind", "parameters", "owner_command", "role"}:
        raise ValueError("unknown drawing reference field")
    owner = obj.get("owner_command")
    return DrawingGeometryReference(
        cast("LiteralReferenceKind", _text(obj.get("kind"))),
        tuple((key, _number(number)) for key, number in _record(obj.get("parameters", {})).items()),
        None if owner is None else _text(owner),
        cast("LiteralReferenceRole", _text(obj.get("role", "geometry"))),
    )


# Explicit aliases keep JSON casts narrow; dataclasses validate actual enum values.

LiteralReferenceKind = Literal["cylindrical_face", "planar_face", "edge"]
LiteralReferenceRole = Literal["geometry", "start", "end", "center"]


def drawing_object_mapping(
    value: DrawingSheet | DrawingView | DrawingAnnotation,
) -> dict[str, object]:
    if isinstance(value, DrawingSheet):
        return {
            "sheet_id": str(value.sheet_id),
            "name": value.name,
            "size_mm": list(value.size_mm),
            "margin_mm": value.margin_mm,
            "projection_angle": value.projection_angle,
            "default_scale": value.default_scale,
            "title": [list(item) for item in value.title],
        }
    if isinstance(value, DrawingView):
        return {
            "view_id": str(value.view_id),
            "sheet_id": str(value.sheet_id),
            "source": {"kind": value.source.kind},
            "basis": {
                "right": list(value.basis.right),
                "up": list(value.basis.up),
                "normal": list(value.basis.normal),
            },
            "parent_id": None if value.parent_id is None else str(value.parent_id),
            "direction": value.direction,
            "anchor_mm": list(value.anchor_mm),
            "offset_mm": list(value.offset_mm),
            "scale": value.scale,
            "inherit_scale": value.inherit_scale,
            "aligned": value.aligned,
            "hidden_lines": value.hidden_lines,
            "tangent_lines": value.tangent_lines,
            "inherit_display": value.inherit_display,
        }
    return {
        "annotation_id": str(value.annotation_id),
        "view_id": str(value.view_id),
        "kind": value.kind,
        "references": [
            {
                "kind": ref.kind,
                "parameters": dict(ref.parameters),
                "owner_command": ref.owner_command,
                "role": ref.role,
            }
            for ref in value.references
        ],
        "position_mm": list(value.position_mm),
        "precision": value.precision,
        "layer": value.layer,
        "prefix": value.prefix,
        "suffix": value.suffix,
    }


def _sheet(obj: Mapping[str, object]) -> DrawingSheet:
    title: list[tuple[str, str]] = []
    for raw in _items(obj.get("title", [])):
        pair = _items(raw)
        if len(pair) != 2:
            raise ValueError("title entries require key and text")
        title.append((_text(pair[0]), _text(pair[1])))
    return DrawingSheet(
        _uuid(obj.get("sheet_id")),
        _text(obj.get("name", "工程图1")),
        cast("Point2", _point(obj.get("size_mm", [297, 210]), 2)),
        _number(obj.get("margin_mm", 10)),
        cast("ProjectionAngle", _text(obj.get("projection_angle", "first"))),
        _number(obj.get("default_scale", 1)),
        tuple(title),
    )


def _view(obj: Mapping[str, object]) -> DrawingView:
    source = _record(obj.get("source", {"kind": "current_part"}))
    if set(source) != {"kind"} or source["kind"] != "current_part":
        raise ValueError("only current_part source is supported")
    basis = _record(obj.get("basis", {"right": [1, 0, 0], "up": [0, 0, 1], "normal": [0, -1, 0]}))
    if set(basis) != {"right", "up", "normal"}:
        raise ValueError("basis requires right/up/normal only")
    parent = obj.get("parent_id")
    return DrawingView(
        _uuid(obj.get("view_id")),
        _uuid(obj.get("sheet_id")),
        SourceBinding(),
        ViewBasis(
            cast("Point3", _point(basis["right"], 3)),
            cast("Point3", _point(basis["up"], 3)),
            cast("Point3", _point(basis["normal"], 3)),
        ),
        None if parent is None else _uuid(parent),
        cast("ViewDirection", _text(obj.get("direction", "front"))),
        cast("Point2", _point(obj.get("anchor_mm", [0, 0]), 2)),
        cast("Point2", _point(obj.get("offset_mm", [0, 0]), 2)),
        _number(obj.get("scale", 1)),
        _boolean(obj.get("inherit_scale", True)),
        _boolean(obj.get("aligned", True)),
        _boolean(obj.get("hidden_lines", True)),
        _boolean(obj.get("tangent_lines", False)),
        _boolean(obj.get("inherit_display", True)),
    )


def _annotation(obj: Mapping[str, object]) -> DrawingAnnotation:
    precision = obj.get("precision", 2)
    if isinstance(precision, bool) or not isinstance(precision, int):
        raise ValueError("annotation precision must be an integer")
    return DrawingAnnotation(
        _uuid(obj.get("annotation_id")),
        _uuid(obj.get("view_id")),
        cast("AnnotationKind", _text(obj.get("kind"))),
        tuple(_reference(ref) for ref in _items(obj.get("references"))),
        cast("Point2", _point(obj.get("position_mm"), 2)),
        precision,
        _text(obj.get("layer", "DIM")),
        _text(obj.get("prefix", "")),
        _text(obj.get("suffix", " mm")),
    )


_FIELDS: dict[str, frozenset[str]] = {
    "sheet": frozenset(
        {"sheet_id", "name", "size_mm", "margin_mm", "projection_angle", "default_scale", "title"}
    ),
    "view": frozenset(
        {
            "view_id",
            "sheet_id",
            "source",
            "basis",
            "parent_id",
            "direction",
            "anchor_mm",
            "offset_mm",
            "scale",
            "inherit_scale",
            "aligned",
            "hidden_lines",
            "tangent_lines",
            "inherit_display",
        }
    ),
    "annotation": frozenset(
        {
            "annotation_id",
            "view_id",
            "kind",
            "references",
            "position_mm",
            "precision",
            "layer",
            "prefix",
            "suffix",
        }
    ),
}


def apply_drawing_command(
    state: DrawingState, command_id: str, params: Mapping[str, object]
) -> DrawingState:
    parts = command_id.split(".")
    if (
        len(parts) != 3
        or parts[0] != "drawing"
        or parts[1] not in _FIELDS
        or parts[2] not in ("create", "update", "delete")
    ):
        raise ValueError("unsupported engineering drawing command")
    _, kind, action = parts
    if kind == "view" and "views" in params:
        if set(params) != {"views"} or action == "delete":
            raise ValueError("invalid drawing view group")
        items = _items(params["views"])
        if not 1 <= len(items) <= 6:
            raise ValueError("view group must contain 1 to 6 views")
        candidate = state
        for item in items:
            candidate = apply_drawing_command(candidate, command_id, _record(item))
        return candidate
    if set(params) - _FIELDS[kind]:
        raise ValueError("unknown drawing object field")
    identity_key = f"{kind}_id"
    identity = _uuid(params.get(identity_key))
    obj = dict(params)
    if action == "delete":
        if set(obj) != {identity_key}:
            raise ValueError("delete only accepts object identity")
        return apply_drawing_operation(
            state, DrawingOperation("delete", cast("ObjectKind", kind), identity)
        )
    if action == "update":
        previous: DrawingSheet | DrawingView | DrawingAnnotation
        if kind == "sheet":
            previous = state.sheet(identity)
        elif kind == "view":
            previous = state.view(identity)
        else:
            matches = [a for a in state.annotations if a.annotation_id == identity]
            if not matches:
                raise ValueError("missing annotation")
            previous = matches[0]
        obj = {**drawing_object_mapping(previous), **obj}
    value = _sheet(obj) if kind == "sheet" else _view(obj) if kind == "view" else _annotation(obj)
    return apply_drawing_operation(
        state, DrawingOperation(cast("Action", action), cast("ObjectKind", kind), identity, value)
    )


ObjectKind = Literal["sheet", "view", "annotation"]
Action = Literal["create", "update", "delete"]
