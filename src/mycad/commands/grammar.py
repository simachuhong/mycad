# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bidirectional CLI grammar (T3 command framework).

ASCII English ``verb key=value ...`` lines. ``parse_line`` and ``to_cli`` are
mutually inverse over validated+normalized params; the registry MUST be
injected (verb resolution walks each spec's ``cli.verb_aliases`` — there is
no module-level verb table).

Value lexemes — exactly four forms, no fifth:
  1. integers ``-?[0-9]+`` and floats (decimal point / scientific notation);
  2. booleans ``true``/``false``;
  3. double-quoted strings with ``\\"`` and ``\\\\`` escapes (for values
     containing spaces or special characters);
  4. bare identifiers ``[+-]?[A-Za-z_][A-Za-z0-9_.+-]*`` (at most one leading
     ``+``/``-``, which must be first) for enums, discriminators and signed
     axes: ``new``/``add``/``cut``, ``plane``/``cylinder``, ``+Z``/``-Z``,
     ``circle``, ``through_all``, ``blind``, ``center``, ``polar``...

Whitespace splits tokens; ``=`` and ``.`` are NOT token boundaries (in
``target_face.axis=+Z`` the key splits at the FIRST ``=`` and ``+Z`` is one
whole token). Number/bool shapes take precedence over the bare form for
keys with no schema type (``true`` is bool, not string) — but where the
schema declares a string (e.g. a string enum), the schema decides and
``s=true`` parses as the STRING ``"true"``. A bare token where the schema
declares a number/integer/boolean is a LEXICAL error (wrong literal form);
an illegal enum VALUE (``mode=banana``) is a SEMANTIC error.

Nesting: objects use flat dotted keys ``key.sub=v``; object-array elements
use flat index keys ``key.0.sub=v`` (isomorphic to validation paths like
``holes.2.radius``); square brackets are ONLY for scalar arrays
``center=[0,0,0]`` and must close within one whitespace-delimited token.

``to_cli`` input is validated (default-filled) + normalized params; output
is ALL keys INCLUDING default-filled ones (``center=[0,0,0]`` and
``mode=new`` are always explicit — no compact form exists). Integer-valued
floats serialize without the decimal point (``0.0`` -> ``0``, ``25.0`` ->
``25``); other floats use shortest-roundtrip repr. Key order is the
``properties`` declaration order of ``params_schema``, recursively (root
``$ref`` -> the referenced def's order).

Examples (each has a parse -> to_cli -> parse round-trip test)::

    cylinder radius=40 height=8 mode=new
    hole target_face.surface=plane target_face.axis=+Z target_face.rank=0 position.kind=center diameter=20 depth.kind=through_all
    fillet edges.0.parent_faces.0.surface=cylinder edges.0.curve=circle radius=2
    hole-pattern base_hole.target_face.surface=plane base_hole.target_face.axis=+Z base_hole.target_face.rank=0 base_hole.position.kind=center base_hole.diameter=6 base_hole.depth.kind=through_all pattern.kind=polar pattern.radius=25 pattern.count=4 pattern.start_angle_deg=0
    extrude profile.type=circle profile.radius=30 distance=10
    box size_x=10 size_y=10 size_z=10 center=[1,2,3]
    cut tool.type=box tool.size_x=5 tool.size_y=5 tool.size_z=5 tool.center=[0,0,-5]

Their canonical ``to_cli`` forms add every default explicitly, e.g. the
first line emits ``cylinder radius=40 height=8 center=[0,0,0] mode=new``.
The verb ``cut`` maps ONLY to ``modify.boolean_cut``; feature-command
subtraction is always the ``mode=cut`` key-value form.

Error layers (mutually exclusive exception types):
  1. lexical/batch structure (unclosed quote, bare ``=``, untokenizable
     value, unclosed scalar-array bracket, bad escape, non-contiguous array
     indices, literal-form mismatch at a schema-typed key) ->
     ``CliSyntaxError`` (message carries the offending token/position; a
     SequenceMatcher suggestion points to the nearest registered verb);
  2. verb layer (legal lexing but the first token is no registered alias,
     e.g. ``cylnder``) -> ``UnknownCommandError(identifier=verb)`` with the
     nearest suggestion in the message;
  3. semantic layer (unknown keys, type errors, bounds, oneOf failures) ->
     ``ValidationError`` with dotted paths, raised by ``validate_params``
     which the bus calls AFTER ``parse_line``.

``#`` comment lines and blank lines are skipped by the SCRIPT reader (T10)
before ``parse_line`` is invoked; ``parse_line`` itself rejects them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from difflib import SequenceMatcher
from typing import cast

from mycad.commands.registry import CommandRegistry
from mycad.commands.validation import schema_matches
from mycad.core.exceptions import CliSyntaxError, UnknownCommandError, ValidationError

__all__ = ["parse_line", "to_cli"]

_BARE_RE = re.compile(r"^[+-]?[A-Za-z_][A-Za-z0-9_.+-]*$")
_INT_RE = re.compile(r"^-?[0-9]+$")
_FLOAT_RE = re.compile(r"^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$")
_REF_PREFIX = "#/$defs/"


# ---------------------------------------------------------------------------
# tokenizer
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Whitespace-split with quote-aware tokens (a quoted region may span spaces)."""
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        start = i
        in_quote = False
        while i < n:
            ch = text[i]
            if in_quote:
                if ch == "\\":
                    if i + 1 >= n or text[i + 1] not in ('"', "\\"):
                        raise CliSyntaxError(f"invalid escape at position {i}: {text[i : i + 2]!r}")
                    i += 2
                    continue
                if ch == '"':
                    in_quote = False
                i += 1
            elif ch == '"':
                in_quote = True
                i += 1
            elif ch.isspace():
                break
            else:
                i += 1
        if in_quote:
            raise CliSyntaxError(f"unclosed quote in token {text[start:]!r}")
        tokens.append(text[start:i])
    return tokens


def _unquote(raw: str, where: str) -> str:
    """Decode a double-quoted value token (only \\" and \\\\ escapes)."""
    chars: list[str] = []
    i = 1
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\\":
            if i + 1 < n and raw[i + 1] in ('"', "\\"):
                chars.append(raw[i + 1])
                i += 2
                continue
            raise CliSyntaxError(f"invalid escape in value for {where!r}: {raw!r}")
        if ch == '"':
            if i != n - 1:
                raise CliSyntaxError(
                    f"unexpected content after closing quote for {where!r}: {raw!r}"
                )
            return "".join(chars)
        chars.append(ch)
        i += 1
    raise CliSyntaxError(f"unclosed quote in value for {where!r}: {raw!r}")


# ---------------------------------------------------------------------------
# schema walking (defensive: unresolvable refs -> None, validator reports them)
# ---------------------------------------------------------------------------


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return cast("Mapping[str, object]", value)
    return None


def _as_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return None


def _deref(schema: object, defs: Mapping[str, object]) -> Mapping[str, object] | None:
    current = _as_mapping(schema)
    seen: set[str] = set()
    while current is not None and "$ref" in current:
        ref = current["$ref"]
        if not isinstance(ref, str) or ref in seen:
            return None
        seen.add(ref)
        name = ref.removeprefix(_REF_PREFIX)
        if not ref.startswith(_REF_PREFIX) or name not in defs:
            return None
        current = _as_mapping(defs[name])
    return current


def _declared_type(schema: object, defs: Mapping[str, object]) -> str | None:
    resolved = _deref(schema, defs)
    if resolved is None:
        return None
    declared = resolved.get("type")
    if isinstance(declared, str):
        return declared
    one_of = resolved.get("oneOf")
    if isinstance(one_of, list):
        branch_types = [_declared_type(branch, defs) for branch in cast("list[object]", one_of)]
        if branch_types and all(t == "object" for t in branch_types):
            return "object"
    return None


def _walk_segment(schema: object, segment: str, defs: Mapping[str, object]) -> object | None:
    resolved = _deref(schema, defs)
    if resolved is None:
        return None
    one_of = resolved.get("oneOf")
    if isinstance(one_of, list):
        results = [_walk_segment(branch, segment, defs) for branch in cast("list[object]", one_of)]
        non_none = [r for r in results if r is not None]
        if not non_none:
            return None
        types = [_declared_type(r, defs) for r in non_none]
        if all(t == types[0] for t in types):
            return non_none[0]
        return None
    properties = _as_mapping(resolved.get("properties"))
    if properties is not None and segment in properties:
        return properties[segment]
    if segment.isdigit() and "items" in resolved:
        return resolved["items"]
    return None


def _schema_at(schema: object, segments: list[str], defs: Mapping[str, object]) -> object | None:
    current: object = schema
    for segment in segments:
        current = _walk_segment(current, segment, defs)
        if current is None:
            return None
    return current


# ---------------------------------------------------------------------------
# value lexing (schema-directed literal forms)
# ---------------------------------------------------------------------------


def _lex_value(raw: str, expected: str | None, where: str, items_expected: str | None) -> object:
    if raw.startswith('"'):
        text = _unquote(raw, where)
        if expected in (None, "string"):
            return text
        raise CliSyntaxError(
            f"token {raw!r} for {where!r}: expected {expected} literal, got a quoted string"
        )
    if raw.startswith("["):
        if expected not in (None, "array"):
            raise CliSyntaxError(
                f"token {raw!r} for {where!r}: expected {expected} literal, got a scalar array"
            )
        if len(raw) < 2 or not raw.endswith("]"):
            raise CliSyntaxError(
                f"unclosed scalar-array bracket for {where!r}: {raw!r} "
                "(brackets must close within one whitespace-delimited token)"
            )
        inner = raw[1:-1]
        if inner == "":
            return []
        return [
            _lex_value(element, items_expected, f"{where}[]", None) for element in inner.split(",")
        ]
    if expected == "object":
        raise CliSyntaxError(
            f"token {raw!r} for {where!r}: object parameters use dotted keys (key.sub=value)"
        )
    if expected == "boolean":
        if raw in ("true", "false"):
            return raw == "true"
        raise CliSyntaxError(f"token {raw!r} for {where!r}: expected boolean literal true/false")
    if _INT_RE.match(raw):
        if expected in (None, "number", "integer"):
            return int(raw)
        if expected == "string":
            return raw
        raise CliSyntaxError(f"token {raw!r} for {where!r}: expected {expected} literal")
    if _FLOAT_RE.match(raw):
        if expected in (None, "number"):
            return float(raw)
        if expected == "string":
            return raw
        raise CliSyntaxError(f"token {raw!r} for {where!r}: expected {expected} literal")
    if raw in ("true", "false"):
        if expected is None:
            return raw == "true"
        if expected == "string":
            return raw
        raise CliSyntaxError(f"token {raw!r} for {where!r}: expected {expected} literal")
    if _BARE_RE.match(raw):
        if expected in (None, "string"):
            return raw
        raise CliSyntaxError(
            f"token {raw!r} for {where!r}: expected {expected} literal, "
            "got a bare identifier (bare tokens are string values: enums/axes)"
        )
    raise CliSyntaxError(f"untokenizable value for {where!r}: {raw!r}")


# ---------------------------------------------------------------------------
# param assembly (flat dotted keys -> nested dicts; digit keys -> lists)
# ---------------------------------------------------------------------------


def _assign(root: dict[str, object], segments: list[str], value: object, where: str) -> None:
    node: dict[str, object] = root
    for segment in segments[:-1]:
        existing = node.get(segment)
        if existing is None:
            child: dict[str, object] = {}
            node[segment] = child
            node = child
        elif isinstance(existing, dict):
            node = cast("dict[str, object]", existing)
        else:
            raise CliSyntaxError(
                f"conflicting dotted keys at {where!r}: {segment!r} already has a scalar value"
            )
    last = segments[-1]
    if isinstance(node.get(last), dict):
        raise CliSyntaxError(
            f"conflicting dotted keys at {where!r}: {last!r} already has an object value"
        )
    node[last] = value


def _materialize(
    schema: object, value: object, defs: Mapping[str, object], path: list[str]
) -> object:
    """Convert digit-keyed dicts to lists where the schema declares arrays."""
    resolved = _deref(schema, defs)
    if resolved is None or "oneOf" in resolved:
        return value
    properties = _as_mapping(resolved.get("properties"))
    node = _as_dict(value)
    if node is not None and properties is not None:
        for key in node:
            if key in properties:
                node[key] = _materialize(properties[key], node[key], defs, [*path, key])
        return node
    if resolved.get("type") == "array":
        items = resolved.get("items")
        if isinstance(value, list):
            elements = cast("list[object]", value)
            return [
                _materialize(items, element, defs, [*path, str(index)])
                for index, element in enumerate(elements)
            ]
        if node is not None and node and all(key.isdigit() for key in node):
            indexes = sorted(int(key) for key in node)
            if indexes != list(range(len(indexes))):
                raise CliSyntaxError(
                    f"non-contiguous array indices at {'.'.join(path) or 'root'}: "
                    f"{sorted(node)} (expected 0..{len(indexes) - 1})"
                )
            return [
                _materialize(items, node[str(index)], defs, [*path, str(index)])
                for index in indexes
            ]
    return value


# ---------------------------------------------------------------------------
# suggestions
# ---------------------------------------------------------------------------


def _nearest_alias(token: str, registry: CommandRegistry) -> str | None:
    aliases: list[str] = []
    for specs in registry.list_by_category().values():
        for spec in specs:
            aliases.extend(spec.cli.verb_aliases)
    lowered = token.lower()
    best: tuple[float, str] | None = None
    for alias in aliases:
        ratio = SequenceMatcher(None, lowered, alias.lower()).ratio()
        if best is None or ratio > best[0] or (ratio == best[0] and alias < best[1]):
            best = (ratio, alias)
    if best is None or best[0] < 0.5:
        return None
    return best[1]


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def parse_line(text: str, registry: CommandRegistry) -> tuple[str, dict[str, object]]:
    """Parse one CLI line to ``(command_id, params)``.

    Lexical and verb-layer errors raise ``CliSyntaxError`` /
    ``UnknownCommandError`` here; SEMANTIC errors (unknown keys, bounds,
    enums, oneOf) are deliberately NOT raised here — the bus calls
    ``validate_params`` next, which owns the ``ValidationError`` layer.
    Defaults are therefore NOT filled by ``parse_line``.
    """
    stripped = text.strip()
    if not stripped:
        raise CliSyntaxError("empty line: the script reader skips blank lines before parse_line")
    if stripped.startswith("#"):
        raise CliSyntaxError("comment line: the script reader skips '#' lines before parse_line")
    tokens = _tokenize(stripped)
    verb = tokens[0]
    spec = registry.resolve_verb(verb)
    if spec is None:
        suggestion = _nearest_alias(verb, registry)
        message = f"unknown command verb {verb!r}"
        if suggestion is not None:
            message += f"; did you mean {suggestion!r}?"
        raise UnknownCommandError(message, identifier=verb)
    defs = registry.schema_defs
    params: dict[str, object] = {}
    for token in tokens[1:]:
        if "=" not in token:
            raise CliSyntaxError(f"token {token!r} is not in key=value form")
        key_raw, _, value_raw = token.partition("=")
        if not key_raw or not value_raw:
            raise CliSyntaxError(f"bare '=' or empty key/value in token {token!r}")
        segments = key_raw.split(".")
        schema_at = _schema_at(spec.params_schema, segments, defs)
        expected = _declared_type(schema_at, defs) if schema_at is not None else None
        items_expected = None
        resolved = _deref(schema_at, defs) if schema_at is not None else None
        if resolved is not None and "items" in resolved:
            items_expected = _declared_type(resolved["items"], defs)
        value = _lex_value(value_raw, expected, key_raw, items_expected)
        _assign(params, segments, value, key_raw)
    result = _materialize(spec.params_schema, params, defs, [])
    return spec.id, cast("dict[str, object]", result)


def _deref_required(schema: object, defs: Mapping[str, object], where: str) -> Mapping[str, object]:
    resolved = _deref(schema, defs)
    if not isinstance(resolved, Mapping):
        raise ValidationError(f"{where}: unresolvable schema $ref (to_cli input contract)")
    return resolved


def _serialize_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, str):
        if _BARE_RE.match(value):
            return value
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise ValidationError(f"cannot serialize value {value!r} into CLI form")


def _emit_object(
    schema: object,
    params: Mapping[str, object],
    defs: Mapping[str, object],
    prefix: str,
) -> list[str]:
    resolved = _deref_required(schema, defs, prefix or "params")
    if isinstance(resolved.get("$defs"), Mapping):
        defs = {**defs, **cast("Mapping[str, object]", resolved["$defs"])}
    present = {key: value for key, value in params.items() if value is not None}
    if "oneOf" in resolved:
        branches = resolved["oneOf"]
        if not isinstance(branches, list):
            raise ValidationError(f"{prefix or 'params'}: malformed oneOf in schema")
        branch_list = cast("list[object]", branches)
        branch = next(
            (
                b
                for b in branch_list
                if schema_matches(cast("Mapping[str, object]", b), present, defs)
            ),
            None,
        )
        if branch is None:
            raise ValidationError(
                f"{prefix or 'params'}: no oneOf branch matches params "
                "(to_cli input must be validated first)"
            )
        return _emit_object(branch, present, defs, prefix)
    properties = resolved.get("properties", {})
    if not isinstance(properties, Mapping):
        raise ValidationError(f"{prefix or 'params'}: schema properties must be an object")
    where = prefix or "params"
    extra = sorted(key for key in present if key not in properties)
    if extra:
        raise ValidationError(
            f"{where}: keys not declared by schema: {', '.join(extra)} "
            "(to_cli input must be validated first)"
        )
    pairs: list[str] = []
    for key, prop_schema in cast("Mapping[str, object]", properties).items():
        if key not in present:
            continue
        full = f"{prefix}.{key}" if prefix else key
        pairs.extend(_emit_value(prop_schema, present[key], defs, full))
    return pairs


def _emit_value(schema: object, value: object, defs: Mapping[str, object], full: str) -> list[str]:
    if isinstance(value, Mapping):
        return _emit_object(schema, cast("Mapping[str, object]", value), defs, full)
    if isinstance(value, list):
        elements = cast("list[object]", value)
        resolved = _deref_required(schema, defs, full)
        items = resolved.get("items")
        if elements and all(isinstance(element, Mapping) for element in elements):
            pairs: list[str] = []
            for index, element in enumerate(elements):
                pairs.extend(_emit_value(items, element, defs, f"{full}.{index}"))
            return pairs
        joined = ",".join(_serialize_scalar(element) for element in elements)
        return [f"{full}=[{joined}]"]
    return [f"{full}={_serialize_scalar(value)}"]


def to_cli(command_id: str, params: Mapping[str, object], registry: CommandRegistry) -> str:
    """Serialize validated+normalized params to the canonical CLI line.

    Emits ALL keys including default-filled ones, in schema ``properties``
    declaration order (recursive; root ``$ref`` -> referenced def order).
    None-valued keys are omitted (normalize_params already deleted them).
    """
    spec = registry.get(command_id)
    verb = spec.cli.verb_aliases[0]
    pairs = _emit_object(spec.params_schema, params, registry.schema_defs, "")
    if not pairs:
        return verb
    return f"{verb} {' '.join(pairs)}"
