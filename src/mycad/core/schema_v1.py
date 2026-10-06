# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Hand-written structural validation for v1 document archives.

Deliberately independent of the T3 command-param validator: archive
checking is a *wire* concern (closed shapes, JSON-pointer error paths),
not a JSON-Schema-subset concern. No IO here — persistence owns files.
"""

from __future__ import annotations

from typing import cast

from mycad.core.exceptions import ValidationError
from mycad.core.selectors import (
    AxisLiteral,
    CurveLiteral,
    EdgeSelector,
    FaceSelector,
)

ARCHIVE_FORMAT = "mycad.document"
ARCHIVE_VERSION = 1

_TOP_LEVEL_KEYS = ("format", "version", "metadata", "commands", "named_groups")
_METADATA_KEYS = ("part_no", "revision", "material", "source", "part_name", "notes")
_COMMAND_KEYS = ("id", "version", "params", "ordinal", "timestamp_utc", "confirmed_by")
_AMENDMENT_KEYS = ("at", "actor", "from_params", "reason")

__all__ = [
    "ARCHIVE_FORMAT",
    "ARCHIVE_VERSION",
    "selector_from_json",
    "validate_archive",
]


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _reject_unknown(data: dict[str, object], allowed: tuple[str, ...], pointer: str) -> None:
    for key in data:
        if key not in allowed:
            raise ValidationError(f"{pointer}/{key}: unknown key (allowed: {list(allowed)})")


def _validate_command(cmd: object, pointer: str) -> None:
    if not isinstance(cmd, dict):
        raise ValidationError(f"{pointer}: expected object")
    entry = cast("dict[str, object]", cmd)
    for key in _COMMAND_KEYS:
        if key not in entry:
            raise ValidationError(f"{pointer}: missing command field {key!r}")
    _reject_unknown(entry, (*_COMMAND_KEYS, "amendments"), pointer)
    if not isinstance(entry["id"], str) or not entry["id"]:
        raise ValidationError(f"{pointer}/id: expected non-empty string")
    if not _is_int(entry["version"]):
        raise ValidationError(f"{pointer}/version: expected integer")
    if not isinstance(entry["params"], dict):
        raise ValidationError(f"{pointer}/params: expected object")
    if not _is_int(entry["ordinal"]) or cast("int", entry["ordinal"]) < 0:
        raise ValidationError(f"{pointer}/ordinal: expected integer >= 0")
    if not isinstance(entry["timestamp_utc"], str):
        raise ValidationError(f"{pointer}/timestamp_utc: expected string")
    if entry["confirmed_by"] is not None and not isinstance(entry["confirmed_by"], str):
        raise ValidationError(f"{pointer}/confirmed_by: expected string or null")
    if "amendments" not in entry:
        return
    if not isinstance(entry["amendments"], list):
        raise ValidationError(f"{pointer}/amendments: expected array")
    amendments = cast("list[object]", entry["amendments"])
    for index, amendment in enumerate(amendments):
        am_ptr = f"{pointer}/amendments/{index}"
        if not isinstance(amendment, dict):
            raise ValidationError(f"{am_ptr}: expected object")
        record = cast("dict[str, object]", amendment)
        _reject_unknown(record, _AMENDMENT_KEYS, am_ptr)
        for key in _AMENDMENT_KEYS:
            if key not in record:
                raise ValidationError(f"{am_ptr}: missing field {key!r}")
        if not (
            isinstance(record["at"], str)
            and isinstance(record["actor"], str)
            and isinstance(record["reason"], str)
            and isinstance(record["from_params"], dict)
        ):
            raise ValidationError(
                f"{am_ptr}: at/actor/reason must be strings, from_params an object"
            )


def _validate_group(group: object, pointer: str) -> None:
    if not isinstance(group, dict):
        raise ValidationError(f"{pointer}: expected object")
    entry = cast("dict[str, object]", group)
    for key in ("name", "faces", "edges"):
        if key not in entry:
            raise ValidationError(f"{pointer}: missing key {key!r} (exactly name/faces/edges)")
    _reject_unknown(entry, ("name", "faces", "edges"), pointer)
    if not isinstance(entry["name"], str) or not entry["name"]:
        raise ValidationError(f"{pointer}/name: expected non-empty string")
    for key in ("faces", "edges"):
        if not isinstance(entry[key], list):
            raise ValidationError(f"{pointer}/{key}: expected array")


def validate_archive(data: object) -> None:
    """Structurally validate a parsed v1 archive; ``ValidationError`` on any drift."""
    if not isinstance(data, dict):
        raise ValidationError("archive: top level must be a JSON object")
    root = cast("dict[str, object]", data)
    for key in _TOP_LEVEL_KEYS:
        if key not in root:
            raise ValidationError(f"archive: missing top-level key {key!r}")
    _reject_unknown(root, _TOP_LEVEL_KEYS, "archive")
    if not isinstance(root["format"], str):
        raise ValidationError("archive/format: expected string")
    if not _is_int(root["version"]):
        raise ValidationError("archive/version: expected integer")
    if not isinstance(root["metadata"], dict):
        raise ValidationError("archive/metadata: expected object")
    metadata = cast("dict[str, object]", root["metadata"])
    for key, value in metadata.items():
        if key not in _METADATA_KEYS:
            raise ValidationError(f"archive/metadata/{key}: unknown metadata key")
        if not isinstance(value, str):
            raise ValidationError(f"archive/metadata/{key}: expected string")
    if not isinstance(root["commands"], list):
        raise ValidationError("archive/commands: expected array")
    commands = cast("list[object]", root["commands"])
    for index, cmd in enumerate(commands):
        _validate_command(cmd, f"commands/{index}")
        _scan_nulls(cmd, f"commands/{index}")
    if not isinstance(root["named_groups"], list):
        raise ValidationError("archive/named_groups: expected array")
    groups = cast("list[object]", root["named_groups"])
    for index, group in enumerate(groups):
        _validate_group(group, f"named_groups/{index}")
        _scan_nulls(group, f"named_groups/{index}")


# ---------------------------------------------------------------------------
# Wire-rule null scan (#round8-2 / #round9-3) and selector decoding
# ---------------------------------------------------------------------------

_SELECTOR_NULL_KEYS = ("axis", "curve", "rank")
_AXES = ("+X", "-X", "+Y", "-Y", "+Z", "-Z")


def _scan_nulls(value: object, pointer: str) -> None:
    """Reject explicit ``null`` under selector keys: omit the key, never null."""
    if isinstance(value, dict):
        for key, item in cast("dict[str, object]", value).items():
            if key in _SELECTOR_NULL_KEYS and item is None:
                raise ValidationError(
                    f"{pointer}/{key}: explicit null violates wire rule (omit the key)"
                )
            _scan_nulls(item, f"{pointer}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(cast("list[object]", value)):
            _scan_nulls(item, f"{pointer}/{index}")


def _face_from_json(data: object, pointer: str) -> FaceSelector:
    """Decode one FaceSelector JSON object (closed shape: surface/axis/rank)."""
    if not isinstance(data, dict):
        raise ValidationError(f"{pointer}: expected object")
    entry = cast("dict[str, object]", data)
    _reject_unknown(entry, ("surface", "axis", "rank"), pointer)
    surface = entry.get("surface")
    if surface not in ("plane", "cylinder"):
        raise ValidationError(f"{pointer}/surface: must be 'plane' or 'cylinder'")
    axis: AxisLiteral | None = None
    if "axis" in entry:
        axis_value = entry["axis"]
        if not isinstance(axis_value, str) or axis_value not in _AXES:
            raise ValidationError(f"{pointer}/axis: must be one of the six signed axes {_AXES}")
        axis = axis_value
    rank: int | None = None
    if "rank" in entry:
        rank_value = entry["rank"]
        if not _is_int(rank_value) or cast("int", rank_value) < 0:
            raise ValidationError(f"{pointer}/rank: expected integer >= 0")
        rank = cast("int", rank_value)
    if surface == "plane" and axis is None:
        raise ValidationError(f"{pointer}/axis: required when surface is 'plane'")
    return FaceSelector(surface=surface, axis=axis, rank=rank)


def _edge_from_json(data: object, pointer: str) -> EdgeSelector:
    """Decode one EdgeSelector JSON object (closed shape: parent_faces/curve)."""
    if not isinstance(data, dict):
        raise ValidationError(f"{pointer}: expected object")
    entry = cast("dict[str, object]", data)
    _reject_unknown(entry, ("parent_faces", "curve"), pointer)
    if not isinstance(entry.get("parent_faces"), list):
        raise ValidationError(f"{pointer}/parent_faces: expected array with minItems 1")
    parents = cast("list[object]", entry["parent_faces"])
    if len(parents) < 1:
        raise ValidationError(f"{pointer}/parent_faces: expected array with minItems 1")
    faces = tuple(
        _face_from_json(parent, f"{pointer}/parent_faces/{index}")
        for index, parent in enumerate(parents)
    )
    curve: CurveLiteral | None = None
    if "curve" in entry:
        curve_value = entry["curve"]
        if not isinstance(curve_value, str) or curve_value not in ("line", "circle"):
            raise ValidationError(f"{pointer}/curve: must be 'line' or 'circle'")
        curve = curve_value
    return EdgeSelector(parent_faces=faces, curve=curve)


def selector_from_json(data: object, pointer: str) -> FaceSelector | EdgeSelector:
    """Decode one selector JSON object: face (has 'surface') or edge (parent_faces)."""
    if not isinstance(data, dict):
        raise ValidationError(f"{pointer}: expected object")
    entry = cast("dict[str, object]", data)
    if "surface" in entry:
        return _face_from_json(entry, pointer)
    if "parent_faces" in entry:
        return _edge_from_json(entry, pointer)
    raise ValidationError(
        f"{pointer}: selector must carry 'surface' (face) or 'parent_faces' (edge)"
    )
