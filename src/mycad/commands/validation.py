# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Self-implemented JSON Schema FIXED-subset validation (T3 command framework).

The keyword list below is exhaustive by design: any keyword outside it raises
``ValidationError`` instead of being silently ignored, so a schema can never
drift beyond what this validator actually implements. The subset is exactly
the 20 keywords mandated by plan lines 229-232:

``type`` (integer/number/string/boolean/array/object; integer rejects bool),
``properties`` + ``required``, ``additionalProperties: false``, ``items``
(single schema for every element), ``minItems``/``maxItems``,
``minimum``/``maximum``/``exclusiveMinimum``/``exclusiveMaximum``,
``minLength``/``maxLength``, ``enum``, ``const`` (Python ``==``),
``default`` (fills missing keys only — never overwrites; an explicit ``null``
on a non-nullable type fails the type/enum check), ``oneOf`` (exactly one
branch validates fully), ``$defs`` + ``$ref`` (only local fragment refs of the
form ``#/$defs/<Name>``; a single shared defs table is injected by the caller
via the ``defs`` parameter — the formal table is T7's
``src/mycad/builtin_commands/defs.py``; an inline ``$defs`` inside a schema
shadows the injected table), and ``description`` (doc-only).

``normalize_params`` (same module, T3 sole owner) runs AFTER validation and
BEFORE any dataclass construction: it deletes ``axis == ""`` from
cylinder-surface FaceSelectors and ``curve == ""`` from EdgeSelectors so the
canonical in-memory and wire form is "key omitted" — never ``None``, never an
empty string. Pure functions, zero IO, stdlib only.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import cast

from mycad.commands.spec import CommandSpec
from mycad.core.exceptions import ValidationError

__all__ = ["normalize_params", "schema_matches", "validate_params"]

#: The FIXED keyword subset. Anything outside this set is an error.
_ALLOWED_KEYWORDS: frozenset[str] = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "enum",
        "const",
        "default",
        "oneOf",
        "$defs",
        "$ref",
        "description",
    }
)

_REF_PREFIX = "#/$defs/"

_ScalarJSON = int | float | str | bool | None


def _path_str(path: list[str]) -> str:
    return ".".join(path)


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    return type(value).__name__


def _schema_object(value: object, where: str) -> dict[str, object]:
    """Narrow ``object`` to a schema dict, raising a defensive error otherwise."""
    if not isinstance(value, dict):
        raise ValidationError(f"{where}: schema must be an object, got {_type_name(value)}")
    return cast("dict[str, object]", value)


def _check_keywords(schema: dict[str, object], where: str) -> None:
    for keyword in schema:
        if keyword not in _ALLOWED_KEYWORDS:
            raise ValidationError(
                f"unsupported schema keyword {keyword!r} at {where}: "
                "outside the fixed subset (silently ignoring it is forbidden)"
            )


def _resolve_ref(
    schema: dict[str, object], defs: Mapping[str, object], active_refs: tuple[str, ...]
) -> dict[str, object]:
    """Resolve a whole-schema ``{"$ref": "#/$defs/<Name>"}`` to its target."""
    ref = schema["$ref"]
    if not isinstance(ref, str) or not ref.startswith(_REF_PREFIX) or ref == _REF_PREFIX:
        raise ValidationError(
            f"unsupported $ref {ref!r}: only local '#/$defs/<Name>' references are allowed"
        )
    name = ref[len(_REF_PREFIX) :]
    if ref in active_refs:
        raise ValidationError(f"circular $ref {ref!r}")
    if name not in defs:
        raise ValidationError(f"$ref {ref!r}: no definition {name!r} in the defs table")
    target = _schema_object(defs[name], f"$ref {ref!r}")
    return target


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _check_type(declared: object, value: object, path: list[str]) -> None:
    where = _path_str(path)
    if declared == "integer":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif declared == "number":
        ok = _is_number(value)
    elif declared == "string":
        ok = isinstance(value, str)
    elif declared == "boolean":
        ok = isinstance(value, bool)
    elif declared == "array":
        ok = isinstance(value, list)
    elif declared == "object":
        ok = isinstance(value, Mapping)
    else:
        raise ValidationError(f"{where}: unsupported type {declared!r} in schema")
    if not ok:
        raise ValidationError(f"{where}: expected {declared}, got {_type_name(value)}")


def _check_numeric_bounds(schema: dict[str, object], value: object, path: list[str]) -> None:
    if not _is_number(value):
        return
    number = cast("int | float", value)
    where = _path_str(path)
    if "minimum" in schema:
        bound = schema["minimum"]
        if _is_number(bound) and number < cast("int | float", bound):
            raise ValidationError(f"{where}: value {value!r} violates minimum {bound}")
    if "maximum" in schema:
        bound = schema["maximum"]
        if _is_number(bound) and number > cast("int | float", bound):
            raise ValidationError(f"{where}: value {value!r} violates maximum {bound}")
    if "exclusiveMinimum" in schema:
        bound = schema["exclusiveMinimum"]
        if _is_number(bound) and number <= cast("int | float", bound):
            raise ValidationError(f"{where}: value {value!r} violates exclusiveMinimum {bound}")
    if "exclusiveMaximum" in schema:
        bound = schema["exclusiveMaximum"]
        if _is_number(bound) and number >= cast("int | float", bound):
            raise ValidationError(f"{where}: value {value!r} violates exclusiveMaximum {bound}")


def _check_string_bounds(schema: dict[str, object], value: object, path: list[str]) -> None:
    if not isinstance(value, str):
        return
    where = _path_str(path)
    if "minLength" in schema:
        bound = schema["minLength"]
        if isinstance(bound, int) and len(value) < bound:
            raise ValidationError(f"{where}: string length {len(value)} violates minLength {bound}")
    if "maxLength" in schema:
        bound = schema["maxLength"]
        if isinstance(bound, int) and len(value) > bound:
            raise ValidationError(f"{where}: string length {len(value)} violates maxLength {bound}")


def _validate(
    schema: object,
    value: object,
    path: list[str],
    defs: Mapping[str, object],
    active_refs: tuple[str, ...] = (),
) -> object:
    """Validate ``value`` against ``schema``; return a default-filled copy."""
    schema_dict = _schema_object(schema, f"schema at {_path_str(path) or 'root'}")
    _check_keywords(schema_dict, f"schema for {_path_str(path) or 'root'}")
    if "$defs" in schema_dict:
        inline_defs = _schema_object(schema_dict["$defs"], "inline $defs")
        defs = {**defs, **inline_defs}
    if "$ref" in schema_dict:
        target = _resolve_ref(schema_dict, defs, active_refs)
        return _validate(target, value, path, defs, (*active_refs, cast(str, schema_dict["$ref"])))

    if "oneOf" in schema_dict:
        return _validate_one_of(schema_dict["oneOf"], value, path, defs, active_refs)

    if "type" in schema_dict:
        _check_type(schema_dict["type"], value, path)
        declared = schema_dict["type"]
        if declared == "object":
            return _validate_object(schema_dict, value, path, defs, active_refs)
        if declared == "array":
            return _validate_array(schema_dict, value, path, defs, active_refs)

    _check_numeric_bounds(schema_dict, value, path)
    _check_string_bounds(schema_dict, value, path)

    if "enum" in schema_dict:
        allowed = schema_dict["enum"]
        if not isinstance(allowed, list) or value not in allowed:
            raise ValidationError(f"{_path_str(path)}: value {value!r} is not in enum {allowed!r}")
    if "const" in schema_dict:
        expected = schema_dict["const"]
        if value != expected:
            raise ValidationError(f"{_path_str(path)}: expected const {expected!r}, got {value!r}")
    return value


def _validate_one_of(
    branches: object,
    value: object,
    path: list[str],
    defs: Mapping[str, object],
    active_refs: tuple[str, ...],
) -> object:
    if not isinstance(branches, list) or not branches:
        raise ValidationError(f"{_path_str(path)}: oneOf requires a non-empty array of subschemas")
    branch_list = cast("list[object]", branches)
    where = _path_str(path)
    filled: list[object] = []
    errors: list[str] = []
    for index, branch in enumerate(branch_list):
        try:
            filled.append(_validate(branch, value, path, defs, active_refs))
        except ValidationError as exc:
            errors.append(f"[{index}] {exc.message}")
    if len(filled) == 1:
        return filled[0]
    if not filled:
        raise ValidationError(
            f"{where}: oneOf matched no branch (expected exactly 1); "
            f"branch errors: {'; '.join(errors)}"
        )
    flags = _branch_matches(branch_list, value, path, defs, active_refs)
    matched_indexes = [str(index) for index, flag in enumerate(flags) if flag]
    raise ValidationError(
        f"{where}: oneOf matched {len(filled)} branches (expected exactly 1): "
        f"branches [{', '.join(matched_indexes)}]"
    )


def _branch_matches(
    branches: object,
    value: object,
    path: list[str],
    defs: Mapping[str, object],
    active_refs: tuple[str, ...],
) -> list[bool]:
    """Return per-branch match flags (True = branch validated fully)."""
    if not isinstance(branches, list):
        return []
    branch_list = cast("list[object]", branches)
    flags: list[bool] = []
    for branch in branch_list:
        try:
            _validate(branch, value, path, defs, active_refs)
        except ValidationError:
            flags.append(False)
        else:
            flags.append(True)
    return flags


def _validate_object(
    schema: dict[str, object],
    value: object,
    path: list[str],
    defs: Mapping[str, object],
    active_refs: tuple[str, ...],
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{_path_str(path)}: expected object, got {_type_name(value)}")
    mapping = cast("Mapping[str, object]", value)
    where = _path_str(path)
    properties = schema.get("properties", {})
    properties_dict = _schema_object(properties, f"properties at {where}")
    additional = schema.get("additionalProperties", True)
    result: dict[str, object] = {}

    required = schema.get("required", [])
    if isinstance(required, list):
        for key in cast("list[object]", required):
            if not isinstance(key, str):
                raise ValidationError(f"required list entries must be strings, got {key!r}")
            if key not in mapping:
                raise ValidationError(f"{_path_str([*path, key])}: required key is missing")

    for key, item in mapping.items():
        if key not in properties_dict:
            if additional is False:
                raise ValidationError(
                    f"{_path_str([*path, key])}: unknown key {key!r} is not declared "
                    "(additionalProperties: false)"
                )
            result[key] = item
            continue
        result[key] = _validate(properties_dict[key], item, [*path, key], defs, active_refs)

    # Fill defaults (missing keys only; never overwrite explicit values) in
    # declaration order so key order follows the schema.
    for key, prop_schema in properties_dict.items():
        if key in result:
            continue
        resolved = prop_schema
        seen: tuple[str, ...] = ()
        while isinstance(resolved, dict) and "$ref" in resolved:
            target = _resolve_ref(cast("dict[str, object]", resolved), defs, seen)
            seen = (*seen, cast(str, resolved["$ref"]))
            resolved = target
        if isinstance(resolved, dict) and "default" in resolved:
            default_schema = cast("dict[str, object]", resolved)
            result[key] = deepcopy(default_schema["default"])
    return result


def _validate_array(
    schema: dict[str, object],
    value: object,
    path: list[str],
    defs: Mapping[str, object],
    active_refs: tuple[str, ...],
) -> list[object]:
    if not isinstance(value, list):
        raise ValidationError(f"{_path_str(path)}: expected array, got {_type_name(value)}")
    items_value = cast("list[object]", value)
    where = _path_str(path)
    min_items = schema.get("minItems")
    if isinstance(min_items, int) and len(items_value) < min_items:
        raise ValidationError(
            f"{where}: array length {len(items_value)} violates minItems {min_items}"
        )
    max_items = schema.get("maxItems")
    if isinstance(max_items, int) and len(items_value) > max_items:
        raise ValidationError(
            f"{where}: array length {len(items_value)} violates maxItems {max_items}"
        )
    if "items" in schema:
        items_schema = schema["items"]
        result: list[object] = []
        for index, element in enumerate(items_value):
            result.append(_validate(items_schema, element, [*path, str(index)], defs, active_refs))
        return result
    return list(items_value)


def validate_params(
    spec: CommandSpec,
    params: Mapping[str, object],
    defs: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Validate ``params`` against ``spec.params_schema`` (fixed subset).

    Returns a fresh, default-filled ``dict[str, object]``; raises
    ``ValidationError`` with dotted field paths on any violation. ``defs`` is
    the single shared ``$defs`` injection point (e.g. the registry's
    ``schema_defs``).
    """
    table: dict[str, object] = dict(defs) if defs is not None else {}
    top_defs = spec.params_schema.get("$defs")
    if isinstance(top_defs, Mapping):
        table = {**table, **cast("Mapping[str, object]", top_defs)}
    result = _validate(spec.params_schema, params, [], table)
    if not isinstance(result, dict):
        raise ValidationError(
            f"root params schema of {spec.id!r} must describe an object, got {_type_name(result)}"
        )
    return cast("dict[str, object]", result)


def schema_matches(
    schema: Mapping[str, object],
    value: object,
    defs: Mapping[str, object] | None = None,
) -> bool:
    """Predicate form of the validator: does ``value`` satisfy ``schema``?

    Shared with the grammar layer (oneOf branch selection in ``to_cli`` and
    dotted-array materialization in ``parse_line``).
    """
    try:
        _validate(schema, value, [], dict(defs) if defs is not None else {})
    except ValidationError:
        return False
    return True


def normalize_params(params: Mapping[str, object]) -> dict[str, object]:
    """Delete empty-string selector keys so "key omitted" is the only form.

    Runs AFTER ``validate_params`` and BEFORE any dataclass construction.
    Rules (recursive over every dict/list at any nesting depth):

    * a FaceSelector-shaped dict with ``surface == "cylinder"`` and
      ``axis == ""`` loses the ``axis`` key (deleted, never replaced);
    * a FaceSelector-shaped dict with ``surface == "plane"`` and ``axis == ""``
      raises a defensive ``ValidationError`` (validation should have caught
      it — the plane branch enum has no empty string);
    * any dict with ``curve == ""`` loses the ``curve`` key (EdgeSelector);
    * missing keys stay missing; no other value is transformed and no
      ``None`` value is ever produced.

    Idempotent: ``normalize_params(normalize_params(x)) == normalize_params(x)``.
    """
    return cast("dict[str, object]", _normalize_value(params))


def _normalize_value(value: object) -> object:
    if isinstance(value, dict):
        mapping = cast("dict[str, object]", value)
        normalized: dict[str, object] = {
            key: _normalize_value(item) for key, item in mapping.items()
        }
        surface = normalized.get("surface")
        if surface == "cylinder" and normalized.get("axis") == "":
            del normalized["axis"]
        elif surface == "plane" and normalized.get("axis") == "":
            raise ValidationError(
                "normalize_params: plane FaceSelector with axis == '' is invalid "
                "(validation should have rejected it)"
            )
        if normalized.get("curve") == "":
            del normalized["curve"]
        return normalized
    if isinstance(value, list):
        return [_normalize_value(item) for item in cast("list[object]", value)]
    return value
